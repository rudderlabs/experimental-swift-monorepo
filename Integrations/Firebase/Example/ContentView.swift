//
//  ContentView.swift
//  FirebaseExample
//
//  Created by Vishal Gupta on 09/11/25.
//

import SwiftUI
import RudderStackAnalytics

struct ContentView: View {
    private var analyticsManager = AnalyticsManager.shared

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
                            analyticsManager.identifyUser()
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
                            analyticsManager.checkoutStartedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Order Completed") {
                            analyticsManager.orderCompletedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Order Refunded") {
                            analyticsManager.orderRefundedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Product List Viewed") {
                            analyticsManager.productListViewedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Cart Viewed") {
                            analyticsManager.cartViewedEvent()
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
                            analyticsManager.productAddedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Product Added to Wishlist") {
                            analyticsManager.productAddedToWishlistEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Product Viewed") {
                            analyticsManager.productViewedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Product Removed") {
                            analyticsManager.productRemovedEvent()
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
                            analyticsManager.paymentInfoEnteredEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Products Searched") {
                            analyticsManager.productsSearchedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Cart Shared") {
                            analyticsManager.cartSharedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Product Shared") {
                            analyticsManager.productSharedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Product Clicked") {
                            analyticsManager.productClickedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Promotion Viewed") {
                            analyticsManager.promotionViewedEvent()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Promotion Clicked") {
                            analyticsManager.promotionClickedEvent()
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
                            analyticsManager.customTrackEventWithoutProperties()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Custom Track (With Properties)") {
                            analyticsManager.customTrackEventWithProperties()
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
                            analyticsManager.screenEventWithoutProperties()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Screen (With Properties)") {
                            analyticsManager.screenEventWithProperties()
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
