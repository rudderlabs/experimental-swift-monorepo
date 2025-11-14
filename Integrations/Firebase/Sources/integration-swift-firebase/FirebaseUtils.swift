//
//  FirebaseUtils.swift
//  integration-swift-firebase
//
//  Created by Vishal Gupta on 09/11/25.
//

import Foundation
import FirebaseAnalytics
import RudderStackAnalytics

/**
 * Firebase Utilities for RudderStack Firebase Integration
 *
 * This class contains constants, mappings, and helper methods for the Firebase integration.
 */
class FirebaseUtils {

    // MARK: - Reserved Keywords

    /// Reserved keywords for identify events
    static let identifyReservedKeywords: Set<String> = ["age", "gender", "interest"]

    /// Reserved keywords for track events
    static let firebaseTrackReservedKeywords: Set<String> = [
        "product_id", "name", "category", "quantity", "price", "currency", "value", "revenue",
        "total", "tax", "shipping", "coupon", "cart_id", "payment_method", "query", "list_id",
        "promotion_id", "creative", "affiliation", "share_via", "products", "order_id",
        AnalyticsParameterScreenName
    ]

    // MARK: - Ecommerce Event Mapping

    /// Ecommerce events mapping
    static let ecommerceEventsMapping: [String: String] = [
        ECommerceEvents.paymentInfoEntered: AnalyticsEventAddPaymentInfo,
        ECommerceEvents.productAdded: AnalyticsEventAddToCart,
        ECommerceEvents.productAddedToWishList: AnalyticsEventAddToWishlist,
        ECommerceEvents.checkoutStarted: AnalyticsEventBeginCheckout,
        ECommerceEvents.orderCompleted: AnalyticsEventPurchase,
        ECommerceEvents.orderRefunded: AnalyticsEventRefund,
        ECommerceEvents.productsSearched: AnalyticsEventSearch,
        ECommerceEvents.cartShared: AnalyticsEventShare,
        ECommerceEvents.productShared: AnalyticsEventShare,
        ECommerceEvents.productViewed: AnalyticsEventViewItem,
        ECommerceEvents.productListViewed: AnalyticsEventViewItemList,
        ECommerceEvents.productRemoved: AnalyticsEventRemoveFromCart,
        ECommerceEvents.productClicked: AnalyticsEventSelectContent,
        ECommerceEvents.promotionViewed: AnalyticsEventViewPromotion,
        ECommerceEvents.promotionClicked: AnalyticsEventSelectPromotion,
        ECommerceEvents.cartViewed: AnalyticsEventViewCart
    ]

    // MARK: - Product Properties Mapping

    /// Product properties mapping
    static let productPropertiesMapping: [String: String] = [
        "product_id": AnalyticsParameterItemID,
        "name": AnalyticsParameterItemName,
        "category": AnalyticsParameterItemCategory,
        "quantity": AnalyticsParameterQuantity,
        "price": AnalyticsParameterPrice
    ]

    // MARK: - Events with Products

    /// Events that support products array
    static let eventWithProductsArray: Set<String> = [
        AnalyticsEventBeginCheckout,
        AnalyticsEventPurchase,
        AnalyticsEventRefund,
        AnalyticsEventViewItemList,
        AnalyticsEventViewCart
    ]

    /// Events that support products at root level
    static let eventWithProductsAtRoot: Set<String> = [
        AnalyticsEventAddToCart,
        AnalyticsEventAddToWishlist,
        AnalyticsEventViewItem,
        AnalyticsEventRemoveFromCart
    ]

    // MARK: - Ecommerce Property Mapping

    /// Ecommerce property mapping
    static let ecommercePropertyMapping: [String: String] = [
        "payment_method": AnalyticsParameterPaymentType,
        "coupon": AnalyticsParameterCoupon,
        "query": AnalyticsParameterSearchTerm,
        "list_id": AnalyticsParameterItemListID,
        "promotion_id": AnalyticsParameterPromotionID,
        "creative": AnalyticsParameterCreativeName,
        "affiliation": AnalyticsParameterAffiliation,
        "share_via": AnalyticsParameterMethod
    ]

    // MARK: - Helper Methods

    /**
     * Trims and formats a key for Firebase
     */
    static func getTrimKey(_ key: String) -> String {
        let trimmedKey = key
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: " ", with: "_")
            .replacingOccurrences(of: "-", with: "_")

        // Limit to 40 characters (Firebase parameter name limit)
        let maxLength = 40
        if trimmedKey.count > maxLength {
            return String(trimmedKey.prefix(maxLength))
        }

        return trimmedKey
    }

    /**
     * Checks if a value is empty
     */
    static func isEmpty(_ value: Any?) -> Bool {
        if value == nil {
            return true
        }

        if let stringValue = value as? String {
            return stringValue.isEmpty
        }

        if let dictValue = value as? [String: Any] {
            return dictValue.isEmpty
        }

        if let arrayValue = value as? [Any] {
            return arrayValue.isEmpty
        }

        return false
    }

    /**
     * Checks if a value is a number
     */
    static func isNumber(_ value: Any?) -> Bool {
        if value is NSNumber {
            return true
        }

        if let stringValue = value as? String {
            return Double(stringValue) != nil
        }

        return false
    }

    /**
     * Converts a value to Double
     * Helper method for numeric conversions
     */
    static func doubleValue(_ value: Any) -> Double {
        if let numberValue = value as? NSNumber {
            return numberValue.doubleValue
        }

        if let stringValue = value as? String, let doubleValue = Double(stringValue) {
            return doubleValue
        }

        return 0.0
    }

    /**
     * Converts a value to Int
     * Helper method for numeric conversions
     */
    static func intValue(_ value: Any) -> Int {
        if let numberValue = value as? NSNumber {
            return numberValue.intValue
        }

        if let stringValue = value as? String, let intValue = Int(stringValue) {
            return intValue
        }

        return 0
    }
}
