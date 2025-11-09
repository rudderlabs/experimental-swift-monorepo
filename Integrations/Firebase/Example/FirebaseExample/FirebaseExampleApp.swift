//
//  FirebaseExampleApp.swift
//  FirebaseExample
//
//  Created by Vishal Gupta on 09/11/25.
//

import SwiftUI
import Combine
import RudderStackAnalytics
import RudderIntegrationFirebase
import FirebaseCore

@main
struct FirebaseExampleApp: App {

    init() {
        setupAnalytics()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }

    private func setupAnalytics() {
        LoggerAnalytics.logLevel = .verbose

        // Configuration for RudderStack Analytics
        let configuration = Configuration(writeKey: "", dataPlaneUrl: "")

        // Initialize Analytics
        let analytics = Analytics(configuration: configuration)

        // Add Firebase Integration
        let firebaseIntegration = FirebaseIntegration()
        analytics.add(plugin: firebaseIntegration)

        // Store analytics instance globally for access in ContentView
        AnalyticsManager.shared.analytics = analytics
    }
}

// Singleton to manage analytics instance
class AnalyticsManager: ObservableObject {
    static let shared = AnalyticsManager()
    @Published var analytics: Analytics?

    private init() {}
}
