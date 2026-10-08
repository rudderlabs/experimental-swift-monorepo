import Foundation

package enum DemoNormalizer {
    package static func normalize(_ value: String) -> String {
        value.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ").lowercased()
    }
}
