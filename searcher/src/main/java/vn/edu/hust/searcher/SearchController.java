package vn.edu.hust.searcher;

import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.apache.lucene.queryparser.classic.ParseException;

import java.io.IOException;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class SearchController {
    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(SearchController.class);
    private final SearchService service;

    public SearchController(SearchService service) {
        this.service = service;
    }

    @GetMapping("/index")
    public Map<String, Object> status() throws IOException {
        return service.status();
    }

    @PostMapping("/index/rebuild")
    public SearchService.IndexReport rebuild() throws IOException {
        return service.rebuild();
    }

    @GetMapping("/search")
    public SearchService.Results search(
            @RequestParam String q,
            @RequestParam(defaultValue = "BM25") SearchService.Mode mode,
            @RequestParam(defaultValue = "BM25") SearchService.Ranking ranking,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "10") int size,
            @RequestParam(name = "top_k", defaultValue = "100") int topK) throws IOException, ParseException {
        return service.search(q, mode, ranking, page, size, topK);
    }

    @ExceptionHandler({IllegalArgumentException.class, ParseException.class, MethodArgumentTypeMismatchException.class})
    public ResponseEntity<Map<String, String>> badRequest(Exception ex) {
        return ResponseEntity.badRequest().body(Map.of("error", ex.getMessage() == null ? "Invalid request" : ex.getMessage()));
    }

    @ExceptionHandler(IOException.class)
    public ResponseEntity<Map<String, String>> ioError(IOException ex) {
        log.error("Failed to read source data or Lucene index", ex);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(Map.of("error", "Cannot read data or index; check server logs and source files"));
    }
}
