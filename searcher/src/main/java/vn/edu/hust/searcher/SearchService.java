package vn.edu.hust.searcher;

import com.fasterxml.jackson.databind.*;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.apache.lucene.analysis.tokenattributes.CharTermAttribute;
import org.apache.lucene.document.*;
import org.apache.lucene.index.*;
import org.apache.lucene.queryparser.classic.*;
import org.apache.lucene.search.*;
import org.apache.lucene.search.similarities.*;
import org.apache.lucene.store.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.locks.ReentrantReadWriteLock;

@Service
public class SearchService implements AutoCloseable {
    public enum Mode { BM25, BOOLEAN, PHRASE, FUZZY, PREFIX }
    public enum Ranking { BM25, TFIDF }
    public record IndexReport(int documents, int skipped, List<String> sources) {}
    public record Hit(String url, String title, String type, float score, String snippet) {}
    public record Results(String query, Mode mode, Ranking ranking, long total, String totalRelation,
                          int page, int size, int topK, int returned, boolean hasNext, List<Hit> hits) {}

    private final Path dataPath;
    private final Path indexPath;
    private final boolean indexOnStartup;
    private final ObjectMapper mapper;
    private final VietnameseAnalyzer analyzer = new VietnameseAnalyzer();
    private final ReentrantReadWriteLock lock = new ReentrantReadWriteLock();
    private Directory directory;
    private SearcherManager manager;

    public SearchService(ObjectMapper mapper,
            @Value("${searcher.data-dir}") String dataDir,
            @Value("${searcher.index-dir}") String indexDir,
            @Value("${searcher.index-on-startup:true}") boolean indexOnStartup) {
        this.mapper = mapper;
        Path workingDirectory = Path.of("").toAbsolutePath();
        Path applicationLocation = SearchPaths.applicationLocation();
        this.dataPath = SearchPaths.resolve(dataDir, "data", workingDirectory, applicationLocation);
        this.indexPath = SearchPaths.resolve(indexDir, "index", workingDirectory, applicationLocation);
        this.indexOnStartup = indexOnStartup;
    }

    @PostConstruct public void init() throws IOException {
        org.slf4j.LoggerFactory.getLogger(SearchService.class)
                .info("Search data directory: {}; index directory: {}", dataPath, indexPath);
        Files.createDirectories(indexPath);
        directory = FSDirectory.open(indexPath);
        // Always provide a valid empty index for a fresh installation.
        if (!DirectoryReader.indexExists(directory)) {
            try (var writer = new IndexWriter(directory, new IndexWriterConfig(analyzer))) {
                writer.commit();
            }
        }
        manager = new SearcherManager(directory, null);
        if (indexOnStartup) {
            if (Files.isRegularFile(dataPath.resolve("content.jsonl"))
                    || Files.isRegularFile(dataPath.resolve("content.json"))) {
                rebuild();
            } else {
                org.slf4j.LoggerFactory.getLogger(SearchService.class)
                        .info("No crawl content yet; keeping current index. Crawl first, then POST /api/index/rebuild.");
            }
        }
    }

    /** Rebuild in one commit; on failure the previous committed snapshot survives. */
    public IndexReport rebuild() throws IOException {
        lock.writeLock().lock();
        try {
            var sources = new ArrayList<String>();
            for (String name : List.of("content.jsonl", "content.json")) {
                if (Files.isRegularFile(dataPath.resolve(name))) sources.add(name);
            }
            if (sources.isEmpty()) throw new IllegalArgumentException("No content.jsonl or content.json in " + dataPath);
            var seen = new HashSet<String>();
            int[] counts = {0, 0};
            var config = new IndexWriterConfig(analyzer).setOpenMode(IndexWriterConfig.OpenMode.CREATE);
            var writer = new IndexWriter(directory, config);
            try {
                for (String source : sources) {
                    Path file = dataPath.resolve(source);
                    if (source.endsWith(".jsonl")) {
                        try (var reader = Files.newBufferedReader(file)) {
                            String line;
                            while ((line = reader.readLine()) != null) {
                                if (line.isBlank()) continue;
                                // Do not publish a partial rebuild when a source is malformed.
                                addRecord(mapper.readTree(line), writer, seen, counts);
                            }
                        }
                    } else {
                        try (var parser = mapper.getFactory().createParser(file.toFile())) {
                            if (parser.nextToken() != com.fasterxml.jackson.core.JsonToken.START_ARRAY)
                                throw new IllegalArgumentException("content.json must be a JSON array");
                            while (parser.nextToken() != com.fasterxml.jackson.core.JsonToken.END_ARRAY) {
                                if (parser.currentToken() == null) throw new IOException("Truncated content.json");
                                addRecord(mapper.readTree(parser), writer, seen, counts);
                            }
                        }
                    }
                }
                writer.commit();
            } catch (IOException | RuntimeException ex) {
                writer.rollback();
                throw ex;
            } finally {
                writer.close();
            }
            manager.maybeRefreshBlocking();
            return new IndexReport(counts[0], counts[1], sources);
        } finally { lock.writeLock().unlock(); }
    }

    private void addRecord(JsonNode node, IndexWriter writer, Set<String> seen, int[] counts) throws IOException {
        String url = text(node, "url", "source_url");
        String content = text(node, "content_text", "content");
        String decision = node.path("decision").asText();
        String status = node.path("status").asText();
        if (!node.isObject() || url.isBlank() || content.isBlank()
                || (!decision.isBlank() && !decision.equals("KEEP"))
                || (!status.isBlank() && !status.equals("success")) || !seen.add(url)) {
            counts[1]++; return;
        }
        var doc = new Document();
        doc.add(new StringField("url", url, Field.Store.YES));
        doc.add(new SortedDocValuesField("url_sort", new org.apache.lucene.util.BytesRef(url)));
        doc.add(new StringField("type", text(node, "type", "document_type"), Field.Store.YES));
        doc.add(new TextField("title", text(node, "title"), Field.Store.YES));
        doc.add(new TextField("content", content, Field.Store.YES));
        writer.addDocument(doc);
        counts[0]++;
    }

    private static String text(JsonNode node, String... fields) {
        for (String field : fields) {
            JsonNode value = node.path(field);
            if (value.isTextual() && !value.asText().isBlank()) return value.asText();
        }
        return "";
    }

    private List<String> tokens(String input) throws IOException {
        var result = new ArrayList<String>();
        try (var stream = analyzer.tokenStream("content", input)) {
            var term = stream.addAttribute(CharTermAttribute.class);
            stream.reset();
            while (stream.incrementToken()) result.add(term.toString());
            stream.end();
        }
        if (result.size() > 32) throw new IllegalArgumentException("Use at most 32 query tokens");
        return result;
    }

    private Query query(String input, Mode mode) throws IOException, ParseException {
        var terms = tokens(input);
        if (terms.isEmpty()) throw new IllegalArgumentException("Query contains no searchable words");
        if (mode == Mode.BM25 || mode == Mode.BOOLEAN) {
            var parser = new MultiFieldQueryParser(new String[]{"title", "content"}, analyzer,
                    Map.of("title", 3f, "content", 1f));
            parser.setAllowLeadingWildcard(false);
            // BM25 is plain text; BOOLEAN explicitly enables Lucene syntax.
            return parser.parse(mode == Mode.BOOLEAN ? input : QueryParser.escape(input));
        }
        var fields = new BooleanQuery.Builder();
        for (String field : List.of("title", "content")) {
            Query fieldQuery;
            if (mode == Mode.PHRASE) {
                var phrase = new PhraseQuery.Builder();
                for (int i = 0; i < terms.size(); i++) phrase.add(new Term(field, terms.get(i)), i);
                fieldQuery = phrase.build();
            } else {
                var all = new BooleanQuery.Builder();
                for (String term : terms) {
                    Query part = mode == Mode.FUZZY ? new FuzzyQuery(new Term(field, term), 1)
                            : new PrefixQuery(new Term(field, term));
                    all.add(part, BooleanClause.Occur.MUST);
                }
                fieldQuery = all.build();
            }
            fields.add(new BoostQuery(fieldQuery, field.equals("title") ? 3f : 1f), BooleanClause.Occur.SHOULD);
        }
        return fields.build();
    }

    public Results search(String input, Mode mode, Ranking ranking, int page, int size) throws IOException, ParseException {
        return search(input, mode, ranking, page, size, 100);
    }

    public Results search(String input, Mode mode, Ranking ranking, int page, int size, int topK) throws IOException, ParseException {
        if (input == null || input.isBlank() || input.length() > 500)
            throw new IllegalArgumentException("q must contain 1–500 characters");
        if (page < 0 || size < 1 || size > 100 || ((long) page + 1) * size > 10000)
            throw new IllegalArgumentException("page >= 0, size 1–100, search window <= 10000");
        if (topK < 1 || topK > 10000) throw new IllegalArgumentException("top_k must be between 1 and 10000");
        Query query = query(input, mode);
        lock.readLock().lock();
        IndexSearcher snapshot = null;
        try {
            snapshot = manager.acquire();
            // Per-request searcher: similarity changes cannot race with other requests.
            var searcher = new IndexSearcher(snapshot.getIndexReader());
            searcher.setSimilarity(ranking == Ranking.TFIDF ? new ClassicSimilarity() : new BM25Similarity());
            // Count every match independently from the bounded global top-k set.
            long total = searcher.count(query);
            int returned = (int) Math.min(total, topK);
            int offset = page * size;
            int end = Math.min(offset + size, returned);
            // Stable URL tie-breaker keeps equal-score documents in the same order across rebuilds.
            var sort = new Sort(SortField.FIELD_SCORE, new SortField("url_sort", SortField.Type.STRING));
            var top = searcher.search(query, Math.max(1, Math.min((page + 1) * size, topK)), sort, true);
            var hits = new ArrayList<Hit>();
            for (int i = offset; i < Math.min(end, top.scoreDocs.length); i++) {
                var hit = top.scoreDocs[i];
                var doc = searcher.storedFields().document(hit.doc);
                String body = doc.get("content");
                hits.add(new Hit(doc.get("url"), doc.get("title"), doc.get("type"), hit.score,
                        body.substring(0, Math.min(body.length(), 300))));
            }
            return new Results(input, mode, ranking, total, "EQUAL_TO", page, size, topK, returned, end < returned, hits);
        } finally {
            if (snapshot != null) manager.release(snapshot);
            lock.readLock().unlock();
        }
    }

    public Map<String, Object> status() throws IOException {
        lock.readLock().lock();
        var searcher = manager.acquire();
        try { return Map.of("documents", searcher.getIndexReader().numDocs(), "dataDir", dataPath.toString(), "indexDir", indexPath.toString()); }
        finally { manager.release(searcher); lock.readLock().unlock(); }
    }

    @PreDestroy @Override public void close() throws IOException {
        if (manager != null) manager.close();
        if (directory != null) directory.close();
        analyzer.close();
    }
}
