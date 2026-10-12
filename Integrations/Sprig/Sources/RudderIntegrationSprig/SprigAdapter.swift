import Foundation
import UIKit
import UserLeapKit

protocol SprigAdapter {
    var sprigInstance: Any? { get set }
    func configure(withEnvironment environmentId: String)
    func setUserIdentifier(_ userId: String)
    func setEmailAddress(_ email: String)
    func setVisitorAttribute(key: String, value: Any)
    func track(eventName: String, properties: [String: Any]?)
    func trackAndPresent(eventName: String, properties: [String: Any]?, from viewController: UIViewController)
    func logout()
    func provideSprigInstance() -> Any
    func registerLoggingListener(_ handler: @escaping (String) -> Void)
    func unregisterLoggingListener()
}

class DefaultSprigAdapter: SprigAdapter {
    var sprigInstance: Any?

    private var sprig: UserLeap? {
        return sprigInstance as? UserLeap
    }

    func configure(withEnvironment environmentId: String) {
        sprig?.configure(withEnvironment: environmentId)
    }

    func setUserIdentifier(_ userId: String) {
        sprig?.setUserIdentifier(userId)
    }

    func setEmailAddress(_ email: String) {
        sprig?.setEmailAddress(email)
    }

    func setVisitorAttribute(key: String, value: Any) {
        guard let sprig = sprig else { return }
        if let stringValue = value as? String {
            sprig.setVisitorAttribute(key: key, value: stringValue)
        } else if let boolValue = value as? Bool {
            sprig.setVisitorAttribute(key: key, boolValue: boolValue)
        } else if let intValue = value as? Int {
            sprig.setVisitorAttribute(key: key, intValue: intValue)
        } else if let doubleValue = value as? Double {
            sprig.setVisitorAttribute(key: key, doubleValue: doubleValue)
        } else if let nsNumber = value as? NSNumber {
            sprig.setVisitorAttribute(key: key, intValue: nsNumber.intValue)
        }
    }

    func track(eventName: String, properties: [String: Any]?) {
        let payload = EventPayload(eventName: eventName, properties: properties)
        sprig?.track(payload: payload)
    }

    func trackAndPresent(eventName: String, properties: [String: Any]?, from viewController: UIViewController) {
        let payload = EventPayload(eventName: eventName, properties: properties)
        sprig?.trackAndPresent(payload: payload, from: viewController)
    }

    func logout() {
        sprig?.logout()
    }

    func provideSprigInstance() -> Any {
        return Sprig.shared
    }

    func registerLoggingListener(_ handler: @escaping (String) -> Void) {
        sprig?.registerEventListener(for: .loggingEvent) { payload in
            guard let message = payload[LifecycleEventDataKey.loggingEventMessage] as? String else { return }
            handler(message)
        }
    }

    func unregisterLoggingListener() {
        sprig?.unregisterAllEventListeners(for: .loggingEvent)
    }
}
