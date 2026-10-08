import Foundation

public struct DemoEvent: Equatable {
    public let name: String
    public let destination: String
    public init(name: String, destination: String) {
        self.name = name
        self.destination = destination
    }
}

public enum DemoSDK {
    public static func resourceMessage() throws -> String {
        let url = Bundle.module.url(forResource: "Fixture", withExtension: "json")!
        let data = try Data(contentsOf: url)
        return (try JSONSerialization.jsonObject(with: data) as! [String: String])["message"]!
    }
    public static func hasPrivacyManifest() -> Bool {
        Bundle.module.url(forResource: "PrivacyInfo", withExtension: "xcprivacy") != nil
    }
}
