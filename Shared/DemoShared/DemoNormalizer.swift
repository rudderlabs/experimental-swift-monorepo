import Foundation

public enum DemoNormalizer {
    public static func normalize(_ value: String) -> String {
        value.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ").lowercased()
    }
}
