//
//  FirebaseTestUtils.swift
//  integration-swift-firebase
//
//  Created by Vishal Gupta on 09/11/25.
//

@testable import integration_swift_firebase

/**
 * Mock implementation for adapter of FirebaseApp
 */
class MockFirebaseAppAdapter: FirebaseAppAdapter {
    var configured = false

    var isConfigured: Bool { configured }

    func configure() {
        configured = true
    }
}

/**
 * Mock implementation for adapter of FirebaseAnalytics
 */
class MockFirebaseAnalyticsAdapter: FirebaseAnalyticsAdapter {
    var setUserIDCalls: [String] = []
    var setUserIDWithNilCalled: Bool = false
    var setUserPropertyCalls: [(name: String, value: String)] = []
    var logEventCalls: [(name: String, parameters: [String: Any]?)] = []
    
    func setUserID(_ id: String?) {
        if let id = id {
            setUserIDCalls.append(id)
        } else {
            setUserIDWithNilCalled = true
        }
    }
    
    func setUserProperty(_ value: String?, forName name: String) {
        if let value = value {
            setUserPropertyCalls.append((name: name, value: value))
        }
    }
    
    func logEvent(_ event: String, parameters: [String: Any]?) {
        logEventCalls.append((name: event, parameters: parameters))
    }
    
    func getAnalyticsInstance() -> Any? {
        return "MockAnalyticsInstance" // Return a mock instance for testing
    }
}

extension Dictionary where Key == String {
    static func + (lhs: [Key: Value], rhs: [Key: Value]) -> [Key: Value] {
        return lhs.merging(rhs) { (_, new) in new }
    }
}
