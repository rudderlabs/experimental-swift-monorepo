// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "SwiftPublicationExperiment",
    platforms: [.iOS(.v15), .macOS(.v12)],
    products: [
        .library(name: "DemoSDK", targets: ["DemoSDK"]),
        .library(name: "DemoSprig", targets: ["DemoSprig"]),
        .library(name: "DemoFirebase", targets: ["DemoFirebase"])
    ],
    dependencies: [.package(url: "https://github.com/apple/swift-collections.git", exact: "1.1.4")],
    targets: [
        .target(name: "DemoSDK", path: "Packages/DemoSDK/Sources/DemoSDK",
                resources: [.copy("PrivacyInfo.xcprivacy"), .copy("Fixture.json")]),
        .target(name: "DemoShared", path: "Shared/DemoShared"),
        .target(name: "DemoSprig", dependencies: ["DemoSDK", "DemoShared"],
                path: "Integrations/Sprig/Sources/DemoSprig"),
        .target(name: "DemoFirebase", dependencies: ["DemoSDK", "DemoShared",
                .product(name: "OrderedCollections", package: "swift-collections")],
                path: "Integrations/Firebase/Sources/DemoFirebase"),
        .testTarget(name: "DemoTests", dependencies: ["DemoSDK", "DemoSprig", "DemoFirebase"])
    ]
)
