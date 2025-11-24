// swift-tools-version: 6.2
// The swift-tools-version declares the minimum version of Swift required to build this package.

import PackageDescription

let package = Package(
    name: "integration-swift-firebase",
    platforms: [
        .iOS(.v15),
        .macOS(.v12),
        .tvOS(.v15),
        .watchOS(.v8)
    ],
    products: [
        // Products define the executables and libraries a package produces, making them visible to other packages.
        .library(
            name: "integration-swift-firebase",
            targets: ["integration-swift-firebase"]
        )
    ],
    dependencies: [
        .package(url: "https://github.com/firebase/firebase-ios-sdk", .upToNextMajor(from: "12.5.0")),
        // TODO: Update rudder-sdk-swift dependency after the stable release of rudder-sdk-swift.
        .package(url: "https://github.com/rudderlabs/rudder-sdk-swift.git", branch: "feat/sdk-502-make-standard-integration-public")
    ],
    targets: [
        // Targets are the basic building blocks of a package, defining a module or a test suite.
        // Targets can depend on other targets in this package and products from dependencies.
        .target(
            name: "integration-swift-firebase",
            dependencies: [
                .product(name: "FirebaseAnalytics", package: "firebase-ios-sdk"),
                .product(name: "FirebaseCore", package: "firebase-ios-sdk"),
                .product(name: "RudderStackAnalytics", package: "rudder-sdk-swift")
            ]
        ),
        .testTarget(
            name: "integration-swift-firebaseTests",
            dependencies: ["integration-swift-firebase"]
        )
    ]
)
