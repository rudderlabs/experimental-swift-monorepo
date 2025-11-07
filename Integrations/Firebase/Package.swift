// swift-tools-version: 6.2
// The swift-tools-version declares the minimum version of Swift required to build this package.

import PackageDescription

let package = Package(
    name: "integration-swift-firebase",
    products: [
        // Products define the executables and libraries a package produces, making them visible to other packages.
        .library(
            name: "integration-swift-firebase",
            targets: ["integration-swift-firebase"]
        ),
    ],
    targets: [
        // Targets are the basic building blocks of a package, defining a module or a test suite.
        // Targets can depend on other targets in this package and products from dependencies.
        .target(
            name: "integration-swift-firebase"
        ),
        .testTarget(
            name: "integration-swift-firebaseTests",
            dependencies: ["integration-swift-firebase"]
        ),
    ]
)
