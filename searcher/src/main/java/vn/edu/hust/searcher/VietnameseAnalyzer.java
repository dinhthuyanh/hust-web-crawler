package vn.edu.hust.searcher;

import org.apache.lucene.analysis.*;
import org.apache.lucene.analysis.standard.StandardTokenizer;
import org.apache.lucene.analysis.miscellaneous.ASCIIFoldingFilter;
import org.apache.lucene.analysis.charfilter.MappingCharFilter;
import org.apache.lucene.analysis.charfilter.NormalizeCharMap;
import java.io.Reader;

/** Word tokens, lower case, Vietnamese accent folding (including đ). */
public class VietnameseAnalyzer extends Analyzer {
    private static final NormalizeCharMap MAP;
    static {
        var builder = new NormalizeCharMap.Builder();
        builder.add("đ", "d");
        builder.add("Đ", "D");
        MAP = builder.build();
    }
    @Override protected Reader initReader(String field, Reader reader) {
        return new MappingCharFilter(MAP, reader);
    }
    @Override protected TokenStreamComponents createComponents(String field) {
        var tokenizer = new StandardTokenizer();
        return new TokenStreamComponents(tokenizer,
                new ASCIIFoldingFilter(new LowerCaseFilter(tokenizer)));
    }
}
