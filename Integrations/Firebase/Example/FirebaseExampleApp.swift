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
class AnalyticsManager {
    static let shared = AnalyticsManager()
    var analytics: Analytics?

    private init() {}
}

extension AnalyticsManager {

    // MARK: - User Identity

    func identifyUser() {
        let traits: [String: Any] = [
            "email": "random@example.com",
            "fname": "FirstName",
            "lname": "LastName",
            "phone": "1234567890"
        ]

        analytics?.identify(userId: "i12345", traits: traits)
        LoggerAnalytics.debug("✅ Identified user with traits")
    }

    // MARK: - Events with Multiple Products

    func checkoutStartedEvent() {
        var properties = getStandardAndCustomProperties()
        properties["products"] = getMultipleProducts()

        analytics?.track(name: "Checkout Started", properties: properties)
        LoggerAnalytics.debug("✅ Tracked Checkout Started event")
    }

    func orderCompletedEvent() {
        // First call with products
        var properties = getStandardAndCustomProperties()
        properties["products"] = getMultipleProducts()
        analytics?.track(name: "Order Completed", properties: properties)

        // Second call with value
        properties = ["value": 200]
        analytics?.track(name: "Order Completed", properties: properties)

        // Third call with total
        properties = ["total": 300]
        analytics?.track(name: "Order Completed", properties: properties)

        LoggerAnalytics.debug("✅ Tracked Order Completed events (3 variations)")
    }

    func orderRefundedEvent() {
        var properties = getStandardAndCustomProperties()
        properties["products"] = getMultipleProducts()

        analytics?.track(name: "Order Refunded", properties: properties)
        LoggerAnalytics.debug("✅ Tracked Order Refunded event")
    }

    func productListViewedEvent() {
        var properties = getStandardAndCustomProperties()
        properties["products"] = getMultipleProducts()

        analytics?.track(name: "Product List Viewed", properties: properties)
        LoggerAnalytics.debug("✅ Tracked Product List Viewed event")
    }

    func cartViewedEvent() {
        var properties = getStandardAndCustomProperties()
        properties["products"] = getMultipleProducts()

        analytics?.track(name: "Cart Viewed", properties: properties)
        LoggerAnalytics.debug("✅ Tracked Cart Viewed event")
    }

    // MARK: - Events with Single Product

    func productAddedEvent() {
        let properties = getStandardCustomAndProductAtRoot()
        analytics?.track(name: "Product Added", properties: properties)
        LoggerAnalytics.debug("✅ Tracked Product Added event")
    }

    func productAddedToWishlistEvent() {
        let properties = getStandardCustomAndProductAtRoot()
        analytics?.track(name: "Product Added to Wishlist", properties: properties)
        LoggerAnalytics.debug("✅ Tracked Product Added to Wishlist event")
    }

    func productViewedEvent() {
        let properties = getStandardCustomAndProductAtRoot()
        analytics?.track(name: "Product Viewed", properties: properties)
        LoggerAnalytics.debug("✅ Tracked Product Viewed event")
    }

    func productRemovedEvent() {
        let properties = getStandardCustomAndProductAtRoot()
        analytics?.track(name: "Product Removed", properties: properties)
        LoggerAnalytics.debug("✅ Tracked Product Removed event")
    }

    // MARK: - Events without Product Properties

    func paymentInfoEnteredEvent() {
        let properties = getStandardAndCustomProperties()
        analytics?.track(name: "Payment Info Entered", properties: properties)
        LoggerAnalytics.debug("✅ Tracked Payment Info Entered event")
    }

    func productsSearchedEvent() {
        let properties = getStandardAndCustomProperties()
        analytics?.track(name: "Products Searched", properties: properties)
        LoggerAnalytics.debug("✅ Tracked Products Searched event")
    }

    func cartSharedEvent() {
        // First call with cart_id
        var properties = getStandardAndCustomProperties()
        properties["cart_id"] = "item value - 1"
        analytics?.track(name: "Cart Shared", properties: properties)

        // Second call with product_id
        properties = getStandardAndCustomProperties()
        properties["product_id"] = "item value - 2"
        analytics?.track(name: "Cart Shared", properties: properties)

        LoggerAnalytics.debug("✅ Tracked Cart Shared events (2 variations)")
    }

    func productSharedEvent() {
        // First call with cart_id
        var properties = getStandardAndCustomProperties()
        properties["cart_id"] = "item value - 1"
        analytics?.track(name: "Product Shared", properties: properties)

        // Second call with product_id
        properties = getStandardAndCustomProperties()
        properties["product_id"] = "item value - 2"
        analytics?.track(name: "Product Shared", properties: properties)

        LoggerAnalytics.debug("✅ Tracked Product Shared events (2 variations)")
    }

    func productClickedEvent() {
        var properties = getStandardAndCustomProperties()
        properties["product_id"] = "Item id - 1"

        analytics?.track(name: "Product Clicked", properties: properties)
        LoggerAnalytics.debug("✅ Tracked Product Clicked event")
    }

    func promotionViewedEvent() {
        var properties = getStandardAndCustomProperties()
        properties["name"] = "promotion name-1"

        analytics?.track(name: "Promotion Viewed", properties: properties)
        LoggerAnalytics.debug("✅ Tracked Promotion Viewed event")
    }

    func promotionClickedEvent() {
        var properties = getStandardAndCustomProperties()
        properties["name"] = "promotion name-1"

        analytics?.track(name: "Promotion Clicked", properties: properties)
        LoggerAnalytics.debug("✅ Tracked Promotion Clicked event")
    }

    // MARK: - Custom Events

    func customTrackEventWithoutProperties() {
        analytics?.track(name: "Track Event 1")
        LoggerAnalytics.debug("✅ Tracked custom event without properties")
    }

    func customTrackEventWithProperties() {
        let properties = getCustomProperties()
        analytics?.track(name: "Track Event 2", properties: properties)
        LoggerAnalytics.debug("✅ Tracked custom event with properties")
    }

    // MARK: - Screen Events

    func screenEventWithoutProperties() {
        analytics?.screen(screenName: "View Controller 1")
        LoggerAnalytics.debug("✅ Tracked screen event without properties")
    }

    func screenEventWithProperties() {
        let properties = getCustomProperties()
        analytics?.screen(screenName: "View Controller 2", properties: properties)
        LoggerAnalytics.debug("✅ Tracked screen event with properties")
    }
}

extension AnalyticsManager {

    private func getMultipleProducts() -> [[String: Any]] {
        let product1: [String: Any] = [
            "product_id": "RSPro1",
            "name": "RSMonopoly1",
            "price": 1000.2,
            "quantity": "100",
            "category": "RSCat1"
        ]

        let product2: [String: Any] = [
            "product_id": "Pro2",
            "name": "Games2",
            "price": "2000.20",
            "quantity": 200,
            "category": "RSCat2"
        ]

        return [product1, product2]
    }

    private func getStandardAndCustomProperties() -> [String: Any] {
        return [
            "revenue": 100.0,
            "payment_method": "payment type 1",
            "coupon": "100% off coupon",
            "query": "Search query",
            "list_id": "item list id 1",
            "promotion_id": "promotion id 1",
            "creative": "creative name 1",
            "affiliation": "affiliation value 1",
            "share_via": "method 1",
            "currency": "INR",
            "shipping": "500",
            "tax": 15,
            "order_id": "transaction id 1",
            "key1": "value 1",
            "key2": 100,
            "key3": 200.25
        ]
    }

    private func getStandardCustomAndProductAtRoot() -> [String: Any] {
        var properties = getStandardAndCustomProperties()

        // Product properties at root
        properties["product_id"] = "RSPro1"
        properties["name"] = "RSMonopoly1"
        properties["price"] = 1000.2
        properties["quantity"] = "100"
        properties["category"] = "RSCat1"

        return properties
    }

    private func getCustomProperties() -> [String: Any] {
        return [
            "key1": "value 1",
            "key2": 100,
            "key3": 200.25,
            "currency": "INR",
            "value": 24.55
        ]
    }
}
