//
//  FirebaseAnalyticsAdapter.swift
//  integration-swift-firebase
//
//  Created by Vishal Gupta on 09/11/25.
//

import Foundation
import FirebaseAnalytics

/**
 * Protocol to wrap FirebaseAnalytics.
 */
protocol FirebaseAnalyticsAdapter {
    func setUserID(_ id: String?)
    func setUserProperty(_ value: String?, forName: String)
    func logEvent(_ name: String, parameters: [String: Any]?)
    func getAnalyticsInstance() -> Any?
}

// MARK: Actual Implementation
class DefaultFirebaseAnalyticsAdapter: FirebaseAnalyticsAdapter {
    func setUserID(_ id: String?) {
        FirebaseAnalytics.Analytics.setUserID(id)
    }

    func setUserProperty(_ value: String?, forName: String) {
        FirebaseAnalytics.Analytics.setUserProperty(value, forName: forName)
    }

    func logEvent(_ name: String, parameters: [String : Any]?) {
        FirebaseAnalytics.Analytics.logEvent(name, parameters: parameters)
    }
    
    func getAnalyticsInstance() -> Any? {
        return FirebaseAnalytics.Analytics.self
    }
}
