package vn.edu.hust.searcher;

import java.net.URISyntaxException;
import java.nio.file.Files;
import java.nio.file.Path;

/** Defaults are project-relative; explicit paths remain relative to the working directory. */
final class SearchPaths {
    private SearchPaths() {}

    static Path projectRoot(Path workingDirectory, Path applicationLocation) {
        for (Path start : new Path[]{workingDirectory, applicationLocation}) {
            for (Path candidate = start.toAbsolutePath().normalize(); candidate != null; candidate = candidate.getParent()) {
                if (Files.isRegularFile(candidate.resolve("crawler_hust.py"))
                        && Files.isRegularFile(candidate.resolve("searcher/pom.xml"))) return candidate;
            }
        }
        throw new IllegalArgumentException("Cannot locate hust-web-crawler project. Set DATA_DIR and INDEX_DIR to absolute paths.");
    }

    static Path resolve(String configured, String projectRelative, Path workingDirectory, Path applicationLocation) {
        if (configured.equals("auto"))
            return projectRoot(workingDirectory, applicationLocation).resolve(projectRelative).normalize();
        Path path = Path.of(configured);
        return (path.isAbsolute() ? path : workingDirectory.resolve(path)).toAbsolutePath().normalize();
    }

    static Path applicationLocation() {
        try {
            return Path.of(SearchPaths.class.getProtectionDomain().getCodeSource().getLocation().toURI());
        } catch (URISyntaxException | IllegalArgumentException ex) {
            // Spring Boot executable archives can expose nested: URLs. The application home
            // points at the outer jar (or target/classes when launched from an IDE).
            return new org.springframework.boot.system.ApplicationHome(SearcherApplication.class).getDir().toPath();
        }
    }
}
