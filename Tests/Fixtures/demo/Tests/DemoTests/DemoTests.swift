import XCTest
import DemoSDK
import DemoSprig
import DemoFirebase

final class DemoTests: XCTestCase {
    func testSDKResources() throws {
        XCTAssertEqual(try DemoSDK.resourceMessage(), "standalone resource loaded")
        XCTAssertTrue(DemoSDK.hasPrivacyManifest())
    }
    func testBothIntegrationsAndVendorDependency() {
        XCTAssertEqual(DemoSprig.track("  Demo   Event ").name, "demo event")
        XCTAssertEqual(DemoFirebase.track([" Demo Event ", "demo event"]).count, 1)
    }
    func testSprigKeepsAnEventNameForWhitespaceInput() {
        XCTAssertEqual(DemoSprig.track(" \n\t ").name, "unnamed event")
        XCTAssertEqual(DemoSprig.track("").name, "unnamed event")
        XCTAssertEqual(DemoSprig.track(" Purchase ").name, "purchase")
    }
}
