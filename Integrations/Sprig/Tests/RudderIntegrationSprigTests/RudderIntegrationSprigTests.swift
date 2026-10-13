import Testing
import Foundation
import UIKit
import RudderStackAnalytics
@testable import RudderIntegrationSprig

@Suite("RudderIntegrationSprig Tests", .serialized)
struct SprigIntegrationTests {

    // MARK: - Test Setup Helpers

    private func createIntegration(mockAdapter: MockSprigAdapter = MockSprigAdapter()) -> (SprigIntegration, MockSprigAdapter) {
        let integration = SprigIntegration(sprigAdapter:mockAdapter)
        return (integration, mockAdapter)
    }

    private func createIdentifyEvent(userId: String? = nil, traits: [String: Any]? = nil) -> IdentifyEvent {
        var event = IdentifyEvent()
        event.userId = userId
        if let traits = traits {
            event.context = (event.context ?? [:]).merging(["traits": AnyCodable(traits)]) { _, new in new }
        }
        return event
    }

    private func createTrackEvent(name: String, properties: [String: Any]? = nil) -> TrackEvent {
        return TrackEvent(event: name, properties: properties)
    }

    /// Runs `body` with `LoggerAnalytics.logLevel` (and optionally the logger) swapped in,
    /// restoring the previous values afterwards. Keeps tests that mutate the shared logger
    /// singleton hermetic from each other.
    private func withLogLevel<T>(_ level: LogLevel, logger: Logger? = nil, body: () throws -> T) throws -> T {
        let previousLevel = LoggerAnalytics.logLevel
        LoggerAnalytics.logLevel = level
        if let logger = logger {
            LoggerAnalytics.setLogger(logger)
        }
        defer {
            LoggerAnalytics.logLevel = previousLevel
            if logger != nil {
                LoggerAnalytics.setLogger(SilentLogger())
            }
        }
        return try body()
    }

    @MainActor
    private func makePresentableViewController() -> (UIViewController, UIWindow) {
        let viewController = UIViewController()
        let window = UIWindow()
        window.rootViewController = viewController
        window.isHidden = false
        return (viewController, window)
    }

    // MARK: - Initialization Tests

    @Test("Given SprigIntegration, when initialized, then has correct default properties")
    func testDefaultInitialization() {
        let integration = SprigIntegration()

        #expect(integration.key == "Sprig")
        #expect(integration.pluginType == .terminal)
        #expect(integration.analytics == nil)
    }

    // MARK: - Create Tests

    @Test("Given valid environmentId, when create is called, then configures Sprig SDK")
    func testCreateWithValidConfig() throws {
        let (integration, mock) = createIntegration()

        try integration.create(destinationConfig: ["environmentId": "test-env-123"])

        #expect(mock.configureCalls.count == 1)
        #expect(mock.configureCalls.first == "test-env-123")
        #expect(mock.sprigInstance as? String == "MockSprigInstance")
    }

    @Test("Given already-initialized integration, when create is called again, then skips re-initialization")
    func testCreateIsIdempotent() throws {
        let (integration, mock) = createIntegration()

        try integration.create(destinationConfig: ["environmentId": "test-env-123"])
        try integration.create(destinationConfig: ["environmentId": "different-env"])

        #expect(mock.configureCalls.count == 1)
        #expect(mock.configureCalls.first == "test-env-123")
    }

    @Test("Given missing environmentId, when create is called, then does not configure Sprig SDK")
    func testCreateWithMissingConfig() throws {
        let (integration, mock) = createIntegration()

        try integration.create(destinationConfig: [:])

        #expect(mock.configureCalls.isEmpty)
    }

    @Test("Given empty environmentId, when create is called, then does not configure Sprig SDK")
    func testCreateWithEmptyEnvironmentId() throws {
        let (integration, mock) = createIntegration()

        try integration.create(destinationConfig: ["environmentId": ""])

        #expect(mock.configureCalls.isEmpty)
    }

    // MARK: - GetDestinationInstance Tests

    @Test("Given uninitialized integration, when getDestinationInstance is called, then returns nil")
    func testGetDestinationInstanceBeforeCreate() {
        let (integration, _) = createIntegration()

        let instance = integration.getDestinationInstance()

        #expect(instance == nil)
    }

    @Test("Given initialized integration, when getDestinationInstance is called, then returns adapter instance")
    func testGetDestinationInstanceAfterCreate() throws {
        let (integration, _) = createIntegration()

        try integration.create(destinationConfig: ["environmentId": "test-env-123"])
        let instance = integration.getDestinationInstance()

        #expect(instance as? String == "MockSprigInstance")
    }

    // MARK: - Identify Tests

    @Test("Given valid userId, when identify is called, then sets user identifier")
    func testIdentifyWithUserId() {
        let (integration, mock) = createIntegration()
        let event = createIdentifyEvent(userId: "user-123")

        integration.identify(payload: event)

        #expect(mock.setUserIdentifierCalls.count == 1)
        #expect(mock.setUserIdentifierCalls.first == "user-123")
    }

    @Test("Given nil userId, when identify is called, then drops event")
    func testIdentifyWithNilUserId() {
        let (integration, mock) = createIntegration()
        let event = createIdentifyEvent(userId: nil)

        integration.identify(payload: event)

        #expect(mock.setUserIdentifierCalls.isEmpty)
    }

    @Test("Given empty userId, when identify is called, then drops event")
    func testIdentifyWithEmptyUserId() {
        let (integration, mock) = createIntegration()
        let event = createIdentifyEvent(userId: "")

        integration.identify(payload: event)

        #expect(mock.setUserIdentifierCalls.isEmpty)
    }

    @Test("Given traits with email, when identify is called, then sets email address")
    func testIdentifyWithEmail() {
        let (integration, mock) = createIntegration()
        let event = createIdentifyEvent(userId: "user-123", traits: ["email": "test@example.com", "name": "Test"])

        integration.identify(payload: event)

        #expect(mock.setEmailAddressCalls.count == 1)
        #expect(mock.setEmailAddressCalls.first == "test@example.com")
    }

    @Test("Given traits with valid attributes, when identify is called, then sets visitor attributes without email")
    func testIdentifyFiltersEmailFromAttributes() {
        let (integration, mock) = createIntegration()
        let event = createIdentifyEvent(userId: "user-123", traits: ["email": "test@example.com", "name": "Test", "age": 30])

        integration.identify(payload: event)

        let captured = Dictionary(uniqueKeysWithValues: mock.setVisitorAttributeCalls.map { ($0.key, $0.value) })
        #expect(captured["email"] == nil)
        #expect(captured["name"] as? String == "Test")
        #expect(captured["age"] as? Int == 30)
    }

    // MARK: - Track Tests

    @Test("Given track event, when no viewController set, then calls track")
    @MainActor
    func testTrackWithoutViewController() {
        let (integration, mock) = createIntegration()
        let event = createTrackEvent(name: "Button Clicked", properties: ["buttonId": "cta-1"])

        integration.track(payload: event)

        #expect(mock.trackCalls.count == 1)
        #expect(mock.trackCalls.first?.eventName == "Button Clicked")
    }

    @Test("Given presentable viewController set, when track is called, then calls trackAndPresent")
    @MainActor
    func testTrackWithViewController() {
        let (integration, mock) = createIntegration()
        let (viewController, _window) = makePresentableViewController()
        integration.setViewController(viewController)
        let event = createTrackEvent(name: "Survey Trigger", properties: ["context": "checkout"])

        integration.track(payload: event)

        #expect(mock.trackAndPresentCalls.count == 1)
        #expect(mock.trackAndPresentCalls.first?.eventName == "Survey Trigger")
        #expect(mock.trackAndPresentCalls.first?.viewController === viewController)
        #expect(mock.trackCalls.isEmpty)
        _ = _window
    }

    @Test("Given viewController not in a window, when track is called, then falls back to plain track")
    @MainActor
    func testTrackFallsBackWhenViewControllerNotPresentable() {
        let (integration, mock) = createIntegration()
        let viewController = UIViewController()
        integration.setViewController(viewController)
        let event = createTrackEvent(name: "Button Clicked")

        integration.track(payload: event)

        #expect(mock.trackCalls.count == 1)
        #expect(mock.trackAndPresentCalls.isEmpty)
    }

    @Test("Given viewController explicitly cleared with nil, when track is called, then falls back to plain track")
    @MainActor
    func testTrackAfterClearingViewController() {
        let (integration, mock) = createIntegration()
        let (viewController, _window) = makePresentableViewController()
        integration.setViewController(viewController)
        integration.setViewController(nil)
        let event = createTrackEvent(name: "Button Clicked")

        integration.track(payload: event)

        #expect(mock.trackCalls.count == 1)
        #expect(mock.trackAndPresentCalls.isEmpty)
        _ = _window
    }

    @Test("Given viewController is held weakly, when host releases it, then integration falls back to plain track")
    @MainActor
    func testViewControllerHeldWeakly() {
        let (integration, mock) = createIntegration()
        autoreleasepool {
            let (viewController, _) = makePresentableViewController()
            integration.setViewController(viewController)
        }
        let event = createTrackEvent(name: "Button Clicked")

        integration.track(payload: event)

        #expect(mock.trackCalls.count == 1)
        #expect(mock.trackAndPresentCalls.isEmpty)
    }

    @Test("Given track is called from a background thread, when VC is presentable, then trackAndPresent runs on the main thread")
    func testTrackDispatchesOnMainThreadWhenPresenting() async {
        let mock = MockSprigAdapter()
        let integration = SprigIntegration(sprigAdapter:mock)
        let window = await MainActor.run { () -> UIWindow in
            let viewController = UIViewController()
            let window = UIWindow()
            window.rootViewController = viewController
            window.isHidden = false
            integration.setViewController(viewController)
            return window
        }

        await withCheckedContinuation { continuation in
            mock.onTrackAndPresent = { continuation.resume() }
            Task.detached {
                integration.track(payload: TrackEvent(event: "Background Event"))
            }
        }

        #expect(mock.trackAndPresentCalls.count == 1)
        #expect(mock.lastTrackAndPresentOnMainThread == true)
        _ = window
    }

    @Test("Given no viewController set, when track is called from a background thread, then plain track runs on the caller thread")
    func testTrackStaysOnCallerThreadWhenNoViewController() async {
        let mock = MockSprigAdapter()
        let integration = SprigIntegration(sprigAdapter: mock)

        await withCheckedContinuation { continuation in
            mock.onTrack = { continuation.resume() }
            Task.detached {
                integration.track(payload: TrackEvent(event: "Background Event"))
            }
        }

        #expect(mock.trackCalls.count == 1)
        #expect(mock.lastTrackOnMainThread == false)
    }

    // MARK: - Logging Listener Tests

    @Test("Given logLevel is not .none, when create is called, then registers logging listener")
    func testCreateRegistersLoggingListener() throws {
        try withLogLevel(.debug) {
            let (integration, mock) = createIntegration()

            try integration.create(destinationConfig: ["environmentId": "test-env-123"])

            #expect(mock.registerLoggingListenerCalls.count == 1)
        }
    }

    @Test("Given logLevel is .none, when create is called, then skips logging listener registration")
    func testCreateSkipsLoggingListenerWhenLogLevelIsNone() throws {
        try withLogLevel(.none) {
            let (integration, mock) = createIntegration()

            try integration.create(destinationConfig: ["environmentId": "test-env-123"])

            #expect(mock.registerLoggingListenerCalls.isEmpty)
        }
    }

    @Test("Given create is called twice, when listener already registered, then does not register again")
    func testCreateDoesNotRegisterLoggingListenerTwice() throws {
        try withLogLevel(.debug) {
            let (integration, mock) = createIntegration()

            try integration.create(destinationConfig: ["environmentId": "test-env-123"])
            try integration.create(destinationConfig: ["environmentId": "test-env-123"])

            #expect(mock.registerLoggingListenerCalls.count == 1)
        }
    }

    @Test("Given registered listener emits a message, when invoked, then forwards to LoggerAnalytics.verbose")
    func testLoggingListenerForwardsMessageToVerbose() throws {
        let capturingLogger = CapturingLogger()
        try withLogLevel(.verbose, logger: capturingLogger) {
            let (integration, mock) = createIntegration()
            try integration.create(destinationConfig: ["environmentId": "test-env-123"])

            mock.registerLoggingListenerCalls.first?("hello from Sprig")

            #expect(capturingLogger.verboseMessages.contains("SprigIntegration: hello from Sprig"))
        }
    }

    // MARK: - Teardown Tests

    @Test("Given logging listener registered, when teardown is called, then unregisters listener")
    func testTeardownUnregistersLoggingListener() throws {
        try withLogLevel(.debug) {
            let (integration, mock) = createIntegration()
            try integration.create(destinationConfig: ["environmentId": "test-env-123"])
            #expect(mock.registerLoggingListenerCalls.count == 1)
            #expect(mock.unregisterLoggingListenerCalled == false)

            integration.teardown()

            #expect(mock.unregisterLoggingListenerCalled == true)
        }
    }

    @Test("Given no logging listener registered, when teardown is called, then does not call unregister")
    func testTeardownDoesNotUnregisterWhenNotRegistered() throws {
        try withLogLevel(.none) {
            let (integration, mock) = createIntegration()
            try integration.create(destinationConfig: ["environmentId": "test-env-123"])
            #expect(mock.registerLoggingListenerCalls.isEmpty)

            integration.teardown()

            #expect(mock.unregisterLoggingListenerCalled == false)
        }
    }

    @Test("Given viewController is set, when teardown is called, then track falls back to plain track")
    @MainActor
    func testTeardownClearsViewController() {
        let (integration, mock) = createIntegration()
        let (viewController, _window) = makePresentableViewController()
        integration.setViewController(viewController)

        integration.teardown()
        integration.track(payload: createTrackEvent(name: "After Teardown"))

        #expect(mock.trackCalls.count == 1)
        #expect(mock.trackAndPresentCalls.isEmpty)
        _ = _window
    }

    @Test("Given teardown was called, when create is called again, then re-registers logging listener")
    func testTeardownAllowsReRegistration() throws {
        try withLogLevel(.debug) {
            let (integration, mock) = createIntegration()
            try integration.create(destinationConfig: ["environmentId": "test-env-123"])
            integration.teardown()

            try integration.create(destinationConfig: ["environmentId": "test-env-123"])

            #expect(mock.registerLoggingListenerCalls.count == 2)
        }
    }

    // MARK: - Reset Tests

    @Test("Given SprigIntegration, when reset is called, then calls logout")
    func testReset() {
        let (integration, mock) = createIntegration()

        integration.reset()

        #expect(mock.logoutCalled)
    }
}

// MARK: - SprigUtils Tests

@Suite("SprigUtils Tests")
struct SprigUtilsTests {

    private func capture(_ traits: [String: Any]) -> (mock: MockSprigAdapter, attributes: [String: Any]) {
        let mock = MockSprigAdapter()
        SprigUtils.setSprigAttributes(traits, adapter: mock)
        let attributes = Dictionary(uniqueKeysWithValues: mock.setVisitorAttributeCalls.map { ($0.key, $0.value) })
        return (mock, attributes)
    }

    @Test("Given traits with email, when setSprigAttributes is called, then email is set via setEmailAddress and excluded from visitor attributes")
    func testSetSprigAttributesRoutesEmailToDedicatedSetter() {
        let (mock, attributes) = capture(["email": "test@example.com", "name": "Test"])

        #expect(mock.setEmailAddressCalls == ["test@example.com"])
        #expect(attributes["email"] == nil)
        #expect(attributes["name"] as? String == "Test")
    }

    @Test("Given key starting with !, when setSprigAttributes is called, then key is excluded")
    func testSetSprigAttributesExcludesExclamationPrefix() {
        let (_, attributes) = capture(["!internal": "value", "valid": "value"])

        #expect(attributes["!internal"] == nil)
        #expect(attributes["valid"] as? String == "value")
    }

    @Test("Given key longer than 255 chars, when setSprigAttributes is called, then key is trimmed to 255 chars")
    func testSetSprigAttributesTrimsLongKeys() {
        let longKey = String(repeating: "a", count: 300)
        let trimmedKey = String(repeating: "a", count: 255)
        let (_, attributes) = capture([longKey: "value", "short": "value"])

        #expect(attributes[longKey] == nil)
        #expect(attributes[trimmedKey] as? String == "value")
        #expect(attributes["short"] as? String == "value")
    }

    @Test("Given key exactly 255 chars, when setSprigAttributes is called, then key is included as-is")
    func testSetSprigAttributesAcceptsBoundaryLengthKey() {
        let boundaryKey = String(repeating: "a", count: 255)
        let (_, attributes) = capture([boundaryKey: "value"])

        #expect(attributes[boundaryKey] as? String == "value")
    }

    @Test("Given unsupported value type, when setSprigAttributes is called, then value is excluded")
    func testSetSprigAttributesExcludesUnsupportedTypes() {
        let (_, attributes) = capture(["array": [1, 2, 3], "valid": "string"])

        #expect(attributes["array"] == nil)
        #expect(attributes["valid"] as? String == "string")
    }

    @Test("Given supported value types, when setSprigAttributes is called, then values are forwarded as-is")
    func testSetSprigAttributesForwardsSupportedTypes() {
        let (_, attributes) = capture([
            "stringVal": "hello",
            "boolVal": true,
            "doubleVal": 3.14,
            "intVal": 42
        ])

        #expect(attributes.count == 4)
        #expect(attributes["stringVal"] as? String == "hello")
        #expect(attributes["boolVal"] as? Bool == true)
        #expect(attributes["doubleVal"] as? Double == 3.14)
        #expect(attributes["intVal"] as? Int == 42)
    }

    @Test("Given NSNumber-wrapped values, when setSprigAttributes is called, then values are forwarded as-is")
    func testSetSprigAttributesAcceptsNSNumber() {
        let (_, attributes) = capture([
            "nsBool": NSNumber(value: true),
            "nsInt": NSNumber(value: Int32(42)),
            "nsInt64": NSNumber(value: Int64(9_000_000_000)),
            "nsDouble": NSNumber(value: 2.5)
        ])

        #expect(attributes.count == 4)
        #expect(attributes["nsBool"] as? Bool == true)
        #expect(attributes["nsInt"] as? Int == 42)
        #expect(attributes["nsInt64"] as? Int64 == 9_000_000_000)
        #expect(attributes["nsDouble"] as? Double == 2.5)
    }
}
