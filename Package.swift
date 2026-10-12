// swift-tools-version: 5.9
import PackageDescription

// Development manifest for every package in this repository. Release exports generate their own manifests.
// make new-integration / make import-integration add lines at the end of each `// @integrations-*` block;
// the core SDK sits above the anchors.
let package = Package(
    name: "SwiftPublicationExperiment",
    platforms: [.iOS(.v15), .macOS(.v12), .tvOS(.v15), .watchOS(.v8)],
    products: [
        .library(name: "RudderStackAnalytics", targets: ["RudderStackAnalytics"]),
        // @integrations-products
        .library(name: "RudderIntegrationSprig", targets: ["RudderIntegrationSprig"]),
        .library(name: "RudderIntegrationFirebase", targets: ["RudderIntegrationFirebase"]),
    ],
    dependencies: [
        // @integrations-dependencies
        .package(url: "https://github.com/UserLeap/userleap-ios-sdk-releases", .upToNextMajor(from: "4.29.0")),
        .package(url: "https://github.com/firebase/firebase-ios-sdk", .upToNextMajor(from: "12.5.0")),
    ],
    targets: [
        .target(name: "RudderStackAnalytics",
                dependencies: [],
                path: "Packages/RudderStackAnalytics/Sources/RudderStackAnalytics",
                resources: [.process("Resources")]),
        .testTarget(name: "RudderStackAnalyticsTests",
                    dependencies: ["RudderStackAnalytics"],
                    path: "Packages/RudderStackAnalytics/Tests/RudderStackAnalyticsTests",
                    exclude: ["TestPlans"],
                    resources: [.process("MockResources")]),
        // @integrations-targets
        .target(name: "RudderIntegrationSprig",
                dependencies: [.product(name: "UserLeapKit", package: "userleap-ios-sdk-releases"), "RudderStackAnalytics"],
                path: "Integrations/Sprig/Sources/RudderIntegrationSprig"),
        .testTarget(name: "RudderIntegrationSprigTests",
                    dependencies: ["RudderIntegrationSprig"],
                    path: "Integrations/Sprig/Tests/RudderIntegrationSprigTests"),
        .target(name: "RudderIntegrationFirebase",
                dependencies: [.product(name: "FirebaseAnalytics", package: "firebase-ios-sdk"), .product(name: "FirebaseCore", package: "firebase-ios-sdk"), "RudderStackAnalytics"],
                path: "Integrations/Firebase/Sources/RudderIntegrationFirebase"),
        .testTarget(name: "RudderIntegrationFirebaseTests",
                    dependencies: ["RudderIntegrationFirebase"],
                    path: "Integrations/Firebase/Tests/RudderIntegrationFirebaseTests"),
    ]
)
