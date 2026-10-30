package vn.edu.hust.searcher;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.*;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static vn.edu.hust.searcher.SearchService.Mode.*;
import static vn.edu.hust.searcher.SearchService.Ranking.TFIDF;

class SearchServiceTest {
    @TempDir Path temp;
    SearchService service;
    Path data;
    @BeforeEach void setup() throws Exception {
        data = Files.createDirectory(temp.resolve("data"));
        Files.writeString(data.resolve("content.jsonl"), """
                {"url":"https://hust.edu.vn/a","title":"Đại học Bách khoa Hà Nội","type":"html","content_text":"Thông tin tuyển sinh đại học năm 2026"}
                {"url":"https://hust.edu.vn/b","title":"Nghiên cứu","type":"html","content_text":"Sinh viên nghiên cứu trí tuệ nhân tạo"}
                {"url":"https://hust.edu.vn/drop","decision":"DROP","content_text":"tuyển sinh"}
                """);
        Files.writeString(data.resolve("content.json"), """
                [{"url":"https://hust.edu.vn/a","content":"duplicate"},
                 {"url":"https://hust.edu.vn/c","title":"Đào tạo","document_type":"html","status":"success","content":"Học bổng quốc tế"},
                 {"url":"https://hust.edu.vn/error","status":"error","content":"tuyển sinh"}]
                """);
        service = new SearchService(new ObjectMapper(), data.toString(), temp.resolve("index").toString(), true);
        service.init();
    }
    @AfterEach void close() throws Exception { service.close(); }

    @Test void startsWithoutDataAndCanIndexAfterCrawling() throws Exception {
        Path freshData = temp.resolve("fresh-data");
        Path freshIndex = temp.resolve("fresh-index");
        try (var fresh = new SearchService(new ObjectMapper(), freshData.toString(), freshIndex.toString(), true)) {
            fresh.init();
            assertThat(fresh.status().get("documents")).isEqualTo(0);
            assertThat(fresh.search("hoc", BM25, SearchService.Ranking.BM25, 0, 10).hits()).isEmpty();
            assertThatThrownBy(fresh::rebuild).isInstanceOf(IllegalArgumentException.class);
            Files.createDirectories(freshData);
            Files.writeString(freshData.resolve("content.jsonl"),
                    "{\"url\":\"https://hust.edu.vn/new\",\"content_text\":\"hoc bong\"}\n");
            assertThat(fresh.rebuild().documents()).isEqualTo(1);
        }
        Files.delete(freshData.resolve("content.jsonl"));
        try (var restarted = new SearchService(new ObjectMapper(), freshData.toString(), freshIndex.toString(), true)) {
            restarted.init();
            assertThat(restarted.status().get("documents")).isEqualTo(1);
        }
    }

    @Test void readsBothSchemasAndDeduplicates() throws Exception {
        assertThat(service.rebuild().documents()).isEqualTo(3);
        assertThat(service.rebuild().skipped()).isEqualTo(3);
        assertThat(service.search("hoc bong", PHRASE, SearchService.Ranking.BM25, 0, 10).hits()).hasSize(1);
    }
    @Test void supportsModesAndRankings() throws Exception {
        for (var ranking : SearchService.Ranking.values()) {
            assertThat(service.search("dai hoc", PHRASE, ranking, 0, 10).hits()).hasSize(1);
            assertThat(service.search("tuyen AND sinh", BOOLEAN, ranking, 0, 10).hits()).hasSize(1);
            assertThat(service.search("tuyen NOT sinh", BOOLEAN, ranking, 0, 10).hits()).isEmpty();
            assertThat(service.search("tuyem", FUZZY, ranking, 0, 10).hits()).hasSize(1);
            assertThat(service.search("tuy", PREFIX, ranking, 0, 10).hits()).hasSize(1);
            assertThat(service.search("đại học", BM25, ranking, 0, 10).hits())
                    .isEqualTo(service.search("dai hoc", BM25, ranking, 0, 10).hits());
            assertThat(service.search("đại học", BM25, ranking, 0, 10).hits().getFirst().url())
                    .isEqualTo("https://hust.edu.vn/a");
        }
    }
    @Test void paginationAndValidation() throws Exception {
        assertThat(service.search("hoc", BM25, SearchService.Ranking.BM25, 0, 1).hits()).hasSize(1);
        assertThat(service.search("hoc", BM25, SearchService.Ranking.BM25, 1, 1).hits()).hasSize(1);
        assertThatThrownBy(() -> service.search(" ", BM25, SearchService.Ranking.BM25, 0, 10)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> service.search("hoc", BM25, SearchService.Ranking.BM25, Integer.MAX_VALUE, 100)).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void rebuildRemovesDeletedDocumentsAndPreservesSnapshotOnFailure() throws Exception {
        Files.writeString(data.resolve("content.jsonl"), "invalid JSON");
        assertThatThrownBy(service::rebuild).isInstanceOf(java.io.IOException.class);
        assertThat(service.search("tuyen", BM25, SearchService.Ranking.BM25, 0, 10).hits()).hasSize(1);
        Files.writeString(data.resolve("content.jsonl"), "");
        Files.writeString(data.resolve("content.json"), "[]");
        assertThat(service.rebuild().documents()).isZero();
        assertThat(service.search("tuyen", BM25, SearchService.Ranking.BM25, 0, 10).hits()).isEmpty();
    }
    @Test void missingSourcesDoNotEraseExistingIndex() throws Exception {
        Files.delete(data.resolve("content.jsonl"));
        Files.delete(data.resolve("content.json"));
        assertThatThrownBy(service::rebuild).isInstanceOf(IllegalArgumentException.class);
        assertThat(service.search("tuyen", BM25, SearchService.Ranking.BM25, 0, 10).hits()).hasSize(1);
    }

    @Test void topKIsGlobalRankedSetIndependentOfPageSize() throws Exception {
        for (var ranking : SearchService.Ranking.values()) {
            var full = service.search("hoc", BM25, ranking, 0, 100, 100);
            var first = service.search("hoc", BM25, ranking, 0, 1, 1);
            var beyond = service.search("hoc", BM25, ranking, 1, 1, 1);
            assertThat(full.total()).isEqualTo(2);
            assertThat(first.total()).isEqualTo(2);
            assertThat(first.returned()).isEqualTo(1);
            assertThat(first.hits()).containsExactly(full.hits().getFirst());
            assertThat(first.hasNext()).isFalse();
            assertThat(beyond.hits()).isEmpty();
            assertThat(beyond.hasNext()).isFalse();
            assertThat(full.hits().getFirst().score()).isGreaterThanOrEqualTo(full.hits().getLast().score());
        }
    }

    @Test void tiesAreStableAndLastPageDoesNotExceedTopK() throws Exception {
        var rows = new java.util.ArrayList<String>();
        for (String name : java.util.List.of("z", "b", "a", "c", "d"))
            rows.add("{\"url\":\"https://hust.edu.vn/" + name + "\",\"content_text\":\"robotics\"}");
        Files.write(data.resolve("content.jsonl"), rows);
        Files.writeString(data.resolve("content.json"), "[]");
        service.rebuild();
        for (var mode : SearchService.Mode.values()) {
            for (var ranking : SearchService.Ranking.values()) {
                var first = service.search("robotics", mode, ranking, 0, 2, 3);
                var last = service.search("robotics", mode, ranking, 1, 2, 3);
                assertThat(first.hits()).extracting(SearchService.Hit::url)
                        .containsExactly("https://hust.edu.vn/a", "https://hust.edu.vn/b");
                assertThat(last.hits()).extracting(SearchService.Hit::url).containsExactly("https://hust.edu.vn/c");
                assertThat(first.hasNext()).isTrue();
                assertThat(last.hasNext()).isFalse();
                assertThat(last.total()).isEqualTo(5);
                assertThat(last.returned()).isEqualTo(3);
            }
        }
    }

    @Test void totalCountIsExactBeyondLuceneDefaultThreshold() throws Exception {
        var rows = new java.util.ArrayList<String>();
        for (int i = 0; i < 1105; i++)
            rows.add("{\"url\":\"https://hust.edu.vn/" + i + "\",\"content_text\":\"robotics\"}");
        Files.write(data.resolve("content.jsonl"), rows);
        Files.writeString(data.resolve("content.json"), "[]");
        service.rebuild();
        var result = service.search("robotics", BM25, TFIDF, 0, 10, 7);
        assertThat(result.total()).isEqualTo(1105);
        assertThat(result.totalRelation()).isEqualTo("EQUAL_TO");
        assertThat(result.hits()).hasSize(7);
        assertThat(result.hasNext()).isFalse();
    }

    @Test void rejectsInvalidTopK() {
        for (int k : new int[]{0, -1, 10001})
            assertThatThrownBy(() -> service.search("hoc", BM25, TFIDF, 0, 10, k))
                    .isInstanceOf(IllegalArgumentException.class);
    }
}
