<p align="center">
  <a href="https://rudderstack.com/">
    <img alt="RudderStack" width="512" src="https://cdn.rudderlabs.com/brand/logo_watermark_light.png">
  </a>
  <br />
  <caption>The Customer Data Platform for Developers</caption>
</p>
<p align="center">
  <b>
    <a href="https://rudderstack.com">Website</a>
    ·
    <a href="https://rudderstack.com/docs/">Documentation</a>
    ·
    <a href="https://rudderstack.com/join-rudderstack-slack-community">Community Slack</a>
  </b>
</p>

---


# Sprig Integration

The Sprig integration allows you to send your event data from RudderStack to Sprig (UserLeap).

> This SDK fully supports both Swift and Objective-C and can be used seamlessly in either type of project.

## Installation

### Swift Package Manager

Add the Sprig integration to your Swift project using Swift Package Manager:

1. In Xcode, go to `File > Add Package Dependencies`
2. Enter the package repository URL: `https://github.com/rudderlabs/integration-swift-sprig` in the search bar
3. Select the version you want to use
4. Select the target to which you want to add the package
5. Finally, click on **Add Package**

Alternatively, add it to your `Package.swift` file:

```swift
// swift-tools-version:5.9
// The swift-tools-version declares the minimum version of Swift required to build this package.

import PackageDescription

let package = Package(
    name: "YourApp",
    products: [
        .library(
            name: "YourApp",
            targets: ["YourApp"]),
    ],
    dependencies: [
        // Add the Sprig integration
        .package(url: "https://github.com/rudderlabs/integration-swift-sprig.git", .upToNextMajor(from: "<latest_version>"))
    ],
    targets: [
        .target(
            name: "YourApp",
            dependencies: [
                .product(name: "RudderIntegrationSprig", package: "integration-swift-sprig")
            ]),
    ]
)
```

## Supported Native Sprig SDK Version

This integration supports UserLeapKit (Sprig) SDK version:

```
4.29.0+
```

### Platform Support

The integration supports the following platform:
- iOS 15.0+

## Usage

Initialize the RudderStack SDK and add the Sprig integration:

```swift
import RudderStackAnalytics
import RudderIntegrationSprig

class AppDelegate: UIResponder, UIApplicationDelegate {

    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {

        // Initialize the RudderStack Analytics SDK
        let config = Configuration(
            writeKey: "<WRITE_KEY>",
            dataPlaneUrl: "<DATA_PLANE_URL>"
        )
        let analytics = Analytics(configuration: config)

        // Add Sprig integration
        let sprigIntegration = SprigIntegration()
        analytics.add(plugin: sprigIntegration)

        return true
    }
}
```

### Setting a View Controller for Surveys

To let Sprig present in-app surveys, hand the integration a view controller it can present from:

```swift
sprigIntegration.setViewController(self)
```

#### When to set it

Set the view controller when it becomes the active presentation context — usually from `viewDidAppear(_:)` of the topmost view controller. The most common pattern is set-on-appear / clear-on-disappear:

```swift
override func viewDidAppear(_ animated: Bool) {
    super.viewDidAppear(animated)
    sprigIntegration.setViewController(self)
}

override func viewWillDisappear(_ animated: Bool) {
    super.viewWillDisappear(animated)
    sprigIntegration.setViewController(nil)
}
```

The explicit `nil` clear is optional — see "Lifetime" below.

#### Lifetime

The integration holds the view controller **weakly**, so it will never keep your view controller alive past its natural lifetime. When the host releases its own reference, the stored reference auto-clears.

You can also clear the reference explicitly by passing `nil`:

```swift
sprigIntegration.setViewController(nil)
```

#### Presentation safety

On a `track` event:

- If no view controller is set, the integration calls plain `Sprig.track(...)` on the caller's thread.
- If a view controller is set, the integration hops to the main thread (so it is safe to call `track` from any thread), verifies the view controller is still presentable — loaded, attached to a window, and not being dismissed — and either calls `Sprig.trackAndPresent(...)` or falls back to plain `Sprig.track(...)` if it is not. The event is still delivered to Sprig.

This means you do not need to worry about clearing the reference before tearing down a view controller — the worst case is that one in-flight `track` event quietly skips presentation.

#### Objective-C

The Objective-C bridge exposes the same API:

```objc
[sprigIntegration setViewController:self];
[sprigIntegration setViewController:nil]; // clear
```

### Sprig SDK Logging

The integration forwards Sprig SDK log messages to the RudderStack logger so they appear alongside the rest of your SDK output.

The Sprig iOS SDK emits log messages without a severity (its `loggingEvent` callback only carries a message string), so the integration forwards every Sprig message at the **`verbose`** level. To see Sprig output, set the RudderStack log level to `.verbose`:

```swift
LoggerAnalytics.logLevel = .verbose
```

When the RudderStack log level is `.none`, the integration skips listener registration entirely and no Sprig output is forwarded.

---

Replace:
- `<WRITE_KEY>`: Your project's write key from the RudderStack dashboard
- `<DATA_PLANE_URL>`: The URL of your RudderStack data plane

---

## Contact us

For more information:

- Email us at [docs@rudderstack.com](mailto:docs@rudderstack.com)
- Join our [Community Slack](https://rudderstack.com/join-rudderstack-slack-community)

## Follow Us

- [RudderStack Blog](https://rudderstack.com/blog/)
- [Slack](https://rudderstack.com/join-rudderstack-slack-community)
- [Twitter](https://twitter.com/rudderstack)
- [YouTube](https://www.youtube.com/channel/UCgV-B77bV_-LOmKYHw8jvBw)
