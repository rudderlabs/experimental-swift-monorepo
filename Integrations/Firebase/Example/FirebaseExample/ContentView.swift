//
//  ContentView.swift
//  FirebaseExample
//
//  Created by Vishal Gupta on 09/11/25.
//

import SwiftUI
import RudderStackAnalytics

struct ContentView: View {
    @StateObject private var analyticsManager = AnalyticsManager.shared
    
    var body: some View {
        NavigationView {
            ScrollView {
                VStack(spacing: 16) {
                    Text("Firebase Integration Example")
                        .font(.title)
                        .fontWeight(.bold)
                        .padding()
                    
                    // User Identity Section
                    VStack(spacing: 12) {
                        Text("User Identity")
                            .font(.headline)
                        
                        Button("Identify User") {
                            identifyUser()
                        }
                        .buttonStyle(PrimaryButtonStyle())
                    }
                    .padding()
                    .background(Color.gray.opacity(0.1))
                    .cornerRadius(10)
                    
                    // Ecommerce Events with Multiple Products
                    VStack(spacing: 12) {
                        Text("Events with Multiple Products")
                            .font(.headline)
                        
                        Button("Checkout Started") {
                            checkoutStartedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        
                        Button("Order Completed") {
                            orderCompletedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        
                        Button("Order Refunded") {
                            orderRefundedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        
                        Button("Product List Viewed") {
                            productListViewedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        
                        Button("Cart Viewed") {
                            cartViewedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                    }
                    .padding()
                    .background(Color.blue.opacity(0.1))
                    .cornerRadius(10)
                    
                    // Ecommerce Events with Single Product
                    VStack(spacing: 12) {
                        Text("Events with Single Product")
                            .font(.headline)
                        
                        Button("Product Added") {
                            productAddedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        
                        Button("Product Added to Wishlist") {
                            productAddedToWishlistEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        
                        Button("Product Viewed") {
                            productViewedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        
                        Button("Product Removed") {
                            productRemovedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                    }
                    .padding()
                    .background(Color.green.opacity(0.1))
                    .cornerRadius(10)
                    
                    // Events without Product Properties
                    VStack(spacing: 12) {
                        Text("Events without Product Properties")
                            .font(.headline)
                        
                        Button("Payment Info Entered") {
                            paymentInfoEnteredEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        
                        Button("Products Searched") {
                            productsSearchedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        
                        Button("Cart Shared") {
                            cartSharedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        
                        Button("Product Shared") {
                            productSharedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        
                        Button("Product Clicked") {
                            productClickedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        
                        Button("Promotion Viewed") {
                            promotionViewedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        
                        Button("Promotion Clicked") {
                            promotionClickedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                    }
                    .padding()
                    .background(Color.orange.opacity(0.1))
                    .cornerRadius(10)
                    
                    // Custom Events
                    VStack(spacing: 12) {
                        Text("Custom Events")
                            .font(.headline)
                        
                        Button("Custom Track (No Properties)") {
                            customTrackEventWithoutProperties()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        
                        Button("Custom Track (With Properties)") {
                            customTrackEventWithProperties()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                    }
                    .padding()
                    .background(Color.purple.opacity(0.1))
                    .cornerRadius(10)
                    
                    // Screen Events
                    VStack(spacing: 12) {
                        Text("Screen Events")
                            .font(.headline)
                        
                        Button("Screen (No Properties)") {
                            screenEventWithoutProperties()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        
                        Button("Screen (With Properties)") {
                            screenEventWithProperties()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                    }
                    .padding()
                    .background(Color.red.opacity(0.1))
                    .cornerRadius(10)
                }
                .padding()
            }
            .navigationTitle("Firebase Example")
        }
    }
}

// MARK: - Event Methods

extension ContentView {
    
    // MARK: - User Identity
    
    private func identifyUser() {
        let traits: [String: Any] = [
            "email": "random@example.com",
            "fname": "FirstName",
            "lname": "LastName",
            "phone": "1234567890"
        ]
        
        analyticsManager.analytics?.identify(userId: "i12345", traits: traits)
        print("✅ Identified user with traits")
    }
    
    // MARK: - Events with Multiple Products
    
    private func checkoutStartedEvent() {
        var properties = getStandardAndCustomProperties()
        properties["products"] = getMultipleProducts()
        
        analyticsManager.analytics?.track(name: "Checkout Started", properties: properties)
        print("✅ Tracked Checkout Started event")
    }
    
    private func orderCompletedEvent() {
        // First call with products
        var properties = getStandardAndCustomProperties()
        properties["products"] = getMultipleProducts()
        analyticsManager.analytics?.track(name: "Order Completed", properties: properties)
        
        // Second call with value
        properties = ["value": 200]
        analyticsManager.analytics?.track(name: "Order Completed", properties: properties)
        
        // Third call with total
        properties = ["total": 300]
        analyticsManager.analytics?.track(name: "Order Completed", properties: properties)
        
        print("✅ Tracked Order Completed events (3 variations)")
    }
    
    private func orderRefundedEvent() {
        var properties = getStandardAndCustomProperties()
        properties["products"] = getMultipleProducts()
        
        analyticsManager.analytics?.track(name: "Order Refunded", properties: properties)
        print("✅ Tracked Order Refunded event")
    }
    
    private func productListViewedEvent() {
        var properties = getStandardAndCustomProperties()
        properties["products"] = getMultipleProducts()
        
        analyticsManager.analytics?.track(name: "Product List Viewed", properties: properties)
        print("✅ Tracked Product List Viewed event")
    }
    
    private func cartViewedEvent() {
        var properties = getStandardAndCustomProperties()
        properties["products"] = getMultipleProducts()
        
        analyticsManager.analytics?.track(name: "Cart Viewed", properties: properties)
        print("✅ Tracked Cart Viewed event")
    }
    
    // MARK: - Events with Single Product
    
    private func productAddedEvent() {
        let properties = getStandardCustomAndProductAtRoot()
        analyticsManager.analytics?.track(name: "Product Added", properties: properties)
        print("✅ Tracked Product Added event")
    }
    
    private func productAddedToWishlistEvent() {
        let properties = getStandardCustomAndProductAtRoot()
        analyticsManager.analytics?.track(name: "Product Added to Wishlist", properties: properties)
        print("✅ Tracked Product Added to Wishlist event")
    }
    
    private func productViewedEvent() {
        let properties = getStandardCustomAndProductAtRoot()
        analyticsManager.analytics?.track(name: "Product Viewed", properties: properties)
        print("✅ Tracked Product Viewed event")
    }
    
    private func productRemovedEvent() {
        let properties = getStandardCustomAndProductAtRoot()
        analyticsManager.analytics?.track(name: "Product Removed", properties: properties)
        print("✅ Tracked Product Removed event")
    }
    
    // MARK: - Events without Product Properties
    
    private func paymentInfoEnteredEvent() {
        let properties = getStandardAndCustomProperties()
        analyticsManager.analytics?.track(name: "Payment Info Entered", properties: properties)
        print("✅ Tracked Payment Info Entered event")
    }
    
    private func productsSearchedEvent() {
        let properties = getStandardAndCustomProperties()
        analyticsManager.analytics?.track(name: "Products Searched", properties: properties)
        print("✅ Tracked Products Searched event")
    }
    
    private func cartSharedEvent() {
        // First call with cart_id
        var properties = getStandardAndCustomProperties()
        properties["cart_id"] = "item value - 1"
        analyticsManager.analytics?.track(name: "Cart Shared", properties: properties)
        
        // Second call with product_id
        properties = getStandardAndCustomProperties()
        properties["product_id"] = "item value - 2"
        analyticsManager.analytics?.track(name: "Cart Shared", properties: properties)
        
        print("✅ Tracked Cart Shared events (2 variations)")
    }
    
    private func productSharedEvent() {
        // First call with cart_id
        var properties = getStandardAndCustomProperties()
        properties["cart_id"] = "item value - 1"
        analyticsManager.analytics?.track(name: "Product Shared", properties: properties)
        
        // Second call with product_id
        properties = getStandardAndCustomProperties()
        properties["product_id"] = "item value - 2"
        analyticsManager.analytics?.track(name: "Product Shared", properties: properties)
        
        print("✅ Tracked Product Shared events (2 variations)")
    }
    
    private func productClickedEvent() {
        var properties = getStandardAndCustomProperties()
        properties["product_id"] = "Item id - 1"
        
        analyticsManager.analytics?.track(name: "Product Clicked", properties: properties)
        print("✅ Tracked Product Clicked event")
    }
    
    private func promotionViewedEvent() {
        var properties = getStandardAndCustomProperties()
        properties["name"] = "promotion name-1"
        
        analyticsManager.analytics?.track(name: "Promotion Viewed", properties: properties)
        print("✅ Tracked Promotion Viewed event")
    }
    
    private func promotionClickedEvent() {
        var properties = getStandardAndCustomProperties()
        properties["name"] = "promotion name-1"
        
        analyticsManager.analytics?.track(name: "Promotion Clicked", properties: properties)
        print("✅ Tracked Promotion Clicked event")
    }
    
    // MARK: - Custom Events
    
    private func customTrackEventWithoutProperties() {
        analyticsManager.analytics?.track(name: "Track Event 1")
        print("✅ Tracked custom event without properties")
    }
    
    private func customTrackEventWithProperties() {
        let properties = getCustomProperties()
        analyticsManager.analytics?.track(name: "Track Event 2", properties: properties)
        print("✅ Tracked custom event with properties")
    }
    
    // MARK: - Screen Events
    
    private func screenEventWithoutProperties() {
        analyticsManager.analytics?.screen(screenName: "View Controller 1")
        print("✅ Tracked screen event without properties")
    }
    
    private func screenEventWithProperties() {
        let properties = getCustomProperties()
        analyticsManager.analytics?.screen(screenName: "View Controller 2", properties: properties)
        print("✅ Tracked screen event with properties")
    }
}

// MARK: - Data Helpers

extension ContentView {
    
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

// MARK: - Button Styles

struct PrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Self.Configuration) -> some View {
        configuration.label
            .padding()
            .frame(maxWidth: .infinity)
            .background(Color.blue)
            .foregroundColor(.white)
            .cornerRadius(8)
            .scaleEffect(configuration.isPressed ? 0.95 : 1.0)
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Self.Configuration) -> some View {
        configuration.label
            .padding(.vertical, 8)
            .padding(.horizontal, 16)
            .frame(maxWidth: .infinity)
            .background(Color.gray.opacity(0.2))
            .foregroundColor(.primary)
            .cornerRadius(6)
            .scaleEffect(configuration.isPressed ? 0.95 : 1.0)
    }
}

#Preview {
    ContentView()
}
