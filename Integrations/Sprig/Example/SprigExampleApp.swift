//
//  SprigExampleApp.swift
//  SprigExample
//
//  Created by Vishal Gupta on 25/04/26.
//

import SwiftUI
import RudderStackAnalytics
import RudderIntegrationSprig

@main
struct SprigExampleApp: App {

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
        let configuration = Configuration(writeKey: "<YOUR_WRITE_KEY>", dataPlaneUrl: "<YOUR_DATA_PLANE_URL>")

        // Initialize Analytics
        let analytics = Analytics(configuration: configuration)

        // Add Sprig Integration
        let sprigIntegration = SprigIntegration()
        analytics.add(plugin: sprigIntegration)

        // Store analytics instance and integration globally for access in ContentView
        AnalyticsManager.shared.analytics = analytics
        AnalyticsManager.shared.sprigIntegration = sprigIntegration
    }
}
