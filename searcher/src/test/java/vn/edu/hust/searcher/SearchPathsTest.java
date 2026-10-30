package vn.edu.hust.searcher;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.*;
import static org.assertj.core.api.Assertions.*;

class SearchPathsTest {
    @TempDir Path temp;

    private Path repository() throws Exception {
        Path root = Files.createDirectories(temp.resolve("hust-web-crawler"));
        Files.createDirectories(root.resolve("searcher/target/classes"));
        Files.writeString(root.resolve("crawler_hust.py"), "");
        Files.writeString(root.resolve("searcher/pom.xml"), "");
        return root;
    }

    @Test void ideWorkingDirectoryAtRepositoryRoot() throws Exception {
        Path root = repository();
        Path classes = root.resolve("searcher/target/classes");
        assertThat(SearchPaths.resolve("auto", "data", root, classes)).isEqualTo(root.resolve("data"));
        assertThat(SearchPaths.resolve("auto", "index", root, classes)).isEqualTo(root.resolve("index"));
    }

    @Test void mavenWorkingDirectoryAtModule() throws Exception {
        Path root = repository();
        assertThat(SearchPaths.resolve("auto", "data", root.resolve("searcher"), root.resolve("searcher/target/classes")))
                .isEqualTo(root.resolve("data"));
        assertThat(SearchPaths.resolve("auto", "index", root.resolve("searcher"), root.resolve("searcher/target/classes")))
                .isEqualTo(root.resolve("index"));
    }

    @Test void jarLaunchedFromUnrelatedDirectory() throws Exception {
        Path root = repository();
        assertThat(SearchPaths.resolve("auto", "data", temp, root.resolve("searcher/target/searcher.jar")))
                .isEqualTo(root.resolve("data"));
    }

    @Test void explicitOverridesAreNotReinterpreted() {
        assertThat(SearchPaths.resolve("custom-data", "data", temp, temp)).isEqualTo(temp.resolve("custom-data"));
        assertThat(SearchPaths.resolve(temp.resolve("external-index").toString(), "index", temp, temp))
                .isEqualTo(temp.resolve("external-index"));
    }

    @Test void missingProjectHasActionableError() {
        assertThatThrownBy(() -> SearchPaths.resolve("auto", "data", temp, temp))
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("DATA_DIR and INDEX_DIR");
    }
}
