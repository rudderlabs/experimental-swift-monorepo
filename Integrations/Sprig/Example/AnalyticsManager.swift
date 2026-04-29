//
//  AnalyticsManager.swift
//  SprigExample
//
//  Created by Vishal Gupta on 25/04/26.
//

import Foundation
import RudderStackAnalytics
import RudderIntegrationSprig

// Singleton to manage analytics instance
class AnalyticsManager {
    static let shared = AnalyticsManager()
    var analytics: Analytics?
    var sprigIntegration: SprigIntegration?

    private init() {}
}

extension AnalyticsManager {

    // MARK: - User Identity

    func identifyUserSimple() {
        analytics?.identify(userId: "test_userid_ios")
        LoggerAnalytics.debug("✅ Identified user (simple)")
    }

    func identifyUser() {
        let traits: [String: Any] = [
            "email": "test@mail.com",
            "key-1": "value",
            "key-2": 100,
            "key-3": 122.56,
            "key-4": true
        ]
        analytics?.identify(userId: "test_userid_ios", traits: traits)
        LoggerAnalytics.debug("✅ Identified user with traits")
    }

    // MARK: - Track Events

    func trackWithoutProperties() {
        analytics?.track(name: "Track event without properties")
        LoggerAnalytics.debug("✅ Tracked event without properties")
    }

    func trackWithProperties() {
        let properties: [String: Any] = [
            "key-5": "value 5",
            "key-6": 200
        ]
        analytics?.track(name: "Track event with properties", properties: properties)
        LoggerAnalytics.debug("✅ Tracked event with properties")
    }

    // MARK: - Reset

    func reset() {
        analytics?.reset()
        LoggerAnalytics.debug("✅ Reset analytics")
    }
}
