import UIKit
import RudderStackAnalytics
@testable import RudderIntegrationSprig

final class CapturingLogger: Logger, @unchecked Sendable {
    private let lock = NSLock()
    private var _verboseMessages: [String] = []

    var verboseMessages: [String] {
        lock.lock(); defer { lock.unlock() }
        return _verboseMessages
    }

    func verbose(log: String) {
        lock.lock(); defer { lock.unlock() }
        _verboseMessages.append(log)
    }
}

final class SilentLogger: Logger, @unchecked Sendable {}

class MockSprigAdapter: SprigAdapter {
    var sprigInstance: Any?
    var configureCalls: [String] = []
    var setUserIdentifierCalls: [String] = []
    var setEmailAddressCalls: [String] = []
    var setVisitorAttributeCalls: [(key: String, value: Any)] = []
    var trackCalls: [(eventName: String, properties: [String: Any]?)] = []
    var trackAndPresentCalls: [(eventName: String, properties: [String: Any]?, viewController: UIViewController)] = []
    var lastTrackOnMainThread: Bool?
    var lastTrackAndPresentOnMainThread: Bool?
    var logoutCalled = false
    var registerLoggingListenerCalls: [(String) -> Void] = []
    var unregisterLoggingListenerCalled = false

    var onTrack: (() -> Void)?
    var onTrackAndPresent: (() -> Void)?

    func configure(withEnvironment environmentId: String) {
        configureCalls.append(environmentId)
    }

    func setUserIdentifier(_ userId: String) {
        setUserIdentifierCalls.append(userId)
    }

    func setEmailAddress(_ email: String) {
        setEmailAddressCalls.append(email)
    }

    func setVisitorAttribute(key: String, value: Any) {
        setVisitorAttributeCalls.append((key: key, value: value))
    }

    func track(eventName: String, properties: [String: Any]?) {
        lastTrackOnMainThread = Thread.isMainThread
        trackCalls.append((eventName: eventName, properties: properties))
        onTrack?()
    }

    func trackAndPresent(eventName: String, properties: [String: Any]?, from viewController: UIViewController) {
        lastTrackAndPresentOnMainThread = Thread.isMainThread
        trackAndPresentCalls.append((eventName: eventName, properties: properties, viewController: viewController))
        onTrackAndPresent?()
    }

    func logout() {
        logoutCalled = true
    }

    func provideSprigInstance() -> Any {
        return "MockSprigInstance"
    }

    func registerLoggingListener(_ handler: @escaping (String) -> Void) {
        registerLoggingListenerCalls.append(handler)
    }

    func unregisterLoggingListener() {
        unregisterLoggingListenerCalled = true
    }
}
