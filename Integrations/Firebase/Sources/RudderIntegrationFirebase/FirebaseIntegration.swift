// The Swift Programming Language
// https://docs.swift.org/swift-book

import Foundation
import FirebaseAnalytics
import RudderStackAnalytics

/**
 * Firebase Integration for RudderStack Swift SDK
 */
public class FirebaseIntegration: IntegrationPlugin, StandardIntegration {

    final let analyticsAdapter: FirebaseAnalyticsAdapter
    final let appAdapter: FirebaseAppAdapter

    internal init(
        analyticsAdapter: FirebaseAnalyticsAdapter,
        appAdapter: FirebaseAppAdapter
    ) {
        self.analyticsAdapter = analyticsAdapter
        self.appAdapter = appAdapter
    }

    public convenience init() {
        self.init(
            analyticsAdapter: DefaultFirebaseAnalyticsAdapter(),
            appAdapter: DefaultFirebaseAppAdapter()
        )
    }

    /**
     Plugin type for firebase integration
     */
    public var pluginType: PluginType = .terminal

    /**
     Reference to the analytics instance
     */
    public var analytics: RudderStackAnalytics.Analytics?

    /**
     Integration key identifier
     */
    public var key: String = "Firebase"

    /**
     * Creates and initializes the Firebase integration
     */
    public func create(destinationConfig: [String: Any]) throws {
        // Ensure Firebase initialization happens on the main thread without capturing objects
        if !self.appAdapter.isConfigured {
            self.appAdapter.configure()
            LoggerAnalytics.debug("Firebase is initialized")
        } else {
            LoggerAnalytics.debug("Firebase core already initialized - skipping Firebase configuration")
        }
    }

    /**
     * Returns the Firebase Analytics instance
     * Required by IntegrationPlugin protocol
     */
    public func getDestinationInstance() -> Any? {
        // Return Firebase Analytics class if Firebase is configured
        return self.appAdapter.isConfigured ? self.analyticsAdapter.getAnalyticsInstance() : nil
    }

    // MARK: - Event Methods

    /**
     * Handles identify events
     */
    public func identify(payload: IdentifyEvent) {
        // Set Firebase user ID if present
        if let userId = payload.userId, !FirebaseUtils.isEmpty(userId) {
            LoggerAnalytics.debug("FirebaseIntegration: Setting userId to firebase")
            self.analyticsAdapter.setUserID(userId)
        }

        // Set user properties from traits
        if let traits = payload.context?["traits"] as? AnyCodable {
            if let traitsDictionary = traits.value as? [String: Any] {
                for (key, value) in traitsDictionary {
                    // Skip userId key to avoid duplication
                    guard key != "userId" else { continue }

                    // Trim and format the key
                    let firebaseKey = FirebaseUtils.getTrimKey(key)

                    // Filter out reserved keywords
                    guard !FirebaseUtils.identifyReservedKeywords.contains(firebaseKey) else { continue }

                    // Set user property with string conversion
                    let stringValue = "\(value)"
                    LoggerAnalytics.debug("FirebaseIntegration: Setting userProperty to Firebase: \(firebaseKey)")
                    self.analyticsAdapter.setUserProperty(stringValue, forName: firebaseKey)
                }
            }
        }
    }

    /**
     * Handles track events
     */
    public func track(payload: TrackEvent) {
        // Check if event name is present
        let eventName = payload.event
        guard !FirebaseUtils.isEmpty(eventName) else {
            LoggerAnalytics.debug("FirebaseIntegration: Since the event name is not present, the track event sent to Firebase has been dropped.")
            return
        }

        let properties = payload.properties?.dictionary?.rawDictionary

        // Handle special "Application Opened" event
        if eventName == "Application Opened" {
            handleApplicationOpenedEvent(properties: properties)
        }
        // Handle ecommerce events
        else if let firebaseEvent = FirebaseUtils.ecommerceEventsMapping[eventName] {
            handleECommerceEvent(eventName: eventName, firebaseEvent: firebaseEvent, properties: properties)
        }
        // Handle custom events
        else {
            handleCustomEvent(eventName: eventName, properties: properties)
        }
    }

    /**
     * Handles screen events
     */
    public func screen(payload: ScreenEvent) {
        // Check if screen name is present
        let screenName = payload.event
        guard !FirebaseUtils.isEmpty(screenName) else {
            LoggerAnalytics.debug("FirebaseIntegration: Since the event name is not present, the screen event sent to Firebase has been dropped.")
            return
        }

        // Create parameters dictionary and set screen name
        var params: [String: Any] = [:]
        params[AnalyticsParameterScreenName] = screenName

        // Attach custom properties
        attachAllCustomProperties(params: &params, properties: payload.properties?.dictionary?.rawDictionary, isECommerceEvent: false)

        // Log screen view event
        LoggerAnalytics.debug("FirebaseIntegration: Logged screen view \"\(screenName)\" to Firebase with properties: \(payload.properties?.dictionary?.rawDictionary ?? [:])")
        self.analyticsAdapter.logEvent(AnalyticsEventScreenView, parameters: params)
    }

    /**
     * Resets user state
     */
    public func reset() {
        // Clear Firebase user ID
        self.analyticsAdapter.setUserID(nil)
        LoggerAnalytics.debug("Reset: Firebase Analytics setUserID:nil")
    }
}

extension FirebaseIntegration {

    // MARK: - Private Track Event Handlers

    /**
     * Handles Application Opened event
     */
    private func handleApplicationOpenedEvent(properties: [String: Any]?) {
        let firebaseEvent = AnalyticsEventAppOpen
        var params: [String: Any] = [:]
        makeFirebaseEvent(firebaseEvent: firebaseEvent, params: &params, properties: properties, isECommerceEvent: false)
    }

    /**
     * Handles ecommerce events with mapping
     */
    private func handleECommerceEvent(eventName: String, firebaseEvent: String, properties: [String: Any]?) {
        var params: [String: Any] = [:]

        if let properties = properties {
            // Handle special parameter mappings for specific events
            handleSpecialECommerceParams(firebaseEvent: firebaseEvent, params: &params, properties: properties)

            // Add constant parameters for specific events
            addConstantParamsForECommerceEvent(params: &params, eventName: eventName)

            // Handle ecommerce-specific properties (revenue, products, currency, etc.)
            handleECommerceEventProperties(params: &params, properties: properties, firebaseEvent: firebaseEvent)
        }

        makeFirebaseEvent(firebaseEvent: firebaseEvent, params: &params, properties: properties, isECommerceEvent: true)
    }

    /**
     * Handles custom events
     */
    private func handleCustomEvent(eventName: String, properties: [String: Any]?) {
        let firebaseEvent = FirebaseUtils.getTrimKey(eventName)
        var params: [String: Any] = [:]
        makeFirebaseEvent(firebaseEvent: firebaseEvent, params: &params, properties: properties, isECommerceEvent: false)
    }

    /**
     * Makes Firebase event with parameters
     */
    private func makeFirebaseEvent(firebaseEvent: String, params: inout [String: Any], properties: [String: Any]?, isECommerceEvent: Bool) {
        attachAllCustomProperties(params: &params, properties: properties, isECommerceEvent: isECommerceEvent)
        LoggerAnalytics.debug("FirebaseIntegration: Logged \"\(firebaseEvent)\" to Firebase with properties: \(properties ?? [:])")
        self.analyticsAdapter.logEvent(firebaseEvent, parameters: params)
    }

    /**
     * Handles special parameter mappings for ecommerce events
     */
    private func handleSpecialECommerceParams(firebaseEvent: String, params: inout [String: Any], properties: [String: Any]) {
        // Handle share events
        if firebaseEvent == AnalyticsEventShare {
            if let cartId = properties["cart_id"], !FirebaseUtils.isEmpty(cartId) {
                params[AnalyticsParameterItemID] = cartId
            } else if let productId = properties["product_id"], !FirebaseUtils.isEmpty(productId) {
                params[AnalyticsParameterItemID] = productId
            }
        }

        // Handle promotion events
        if firebaseEvent == AnalyticsEventViewPromotion || firebaseEvent == AnalyticsEventSelectPromotion {
            if let name = properties["name"], !FirebaseUtils.isEmpty(name) {
                params[AnalyticsParameterPromotionName] = name
            }
        }

        // Handle select content events
        if firebaseEvent == AnalyticsEventSelectContent {
            if let productId = properties["product_id"], !FirebaseUtils.isEmpty(productId) {
                params[AnalyticsParameterItemID] = productId
            }
            params[AnalyticsParameterContentType] = "product"
        }
    }

    /**
     * Adds constant parameters for ecommerce events
     */
    private func addConstantParamsForECommerceEvent(params: inout [String: Any], eventName: String) {
        switch eventName {
        case ECommerceEvents.productShared:
            params[AnalyticsParameterContentType] = "product"
        case ECommerceEvents.cartShared:
            params[AnalyticsParameterContentType] = "cart"
        default:
            break
        }
    }

    /**
     * Handles ecommerce-specific properties like revenue, products, currency
     */
    private func handleECommerceEventProperties(params: inout [String: Any], properties: [String: Any], firebaseEvent: String) {
        // Handle revenue/value mapping
        if let revenue = properties["revenue"], FirebaseUtils.isNumber(revenue) {
            params[AnalyticsParameterValue] = FirebaseUtils.doubleValue(revenue)
        } else if let value = properties["value"], FirebaseUtils.isNumber(value) {
            params[AnalyticsParameterValue] = FirebaseUtils.doubleValue(value)
        } else if let total = properties["total"], FirebaseUtils.isNumber(total) {
            params[AnalyticsParameterValue] = FirebaseUtils.doubleValue(total)
        }

        // Handle products array or root-level products
        if FirebaseUtils.eventWithProductsArray.contains(firebaseEvent), let _ = properties["products"] {
            handleProducts(params: &params, properties: properties, isProductsArray: true)
        }

        if FirebaseUtils.eventWithProductsAtRoot.contains(firebaseEvent) {
            handleProducts(params: &params, properties: properties, isProductsArray: false)
        }

        // Handle currency
        if let currency = properties["currency"] {
            params[AnalyticsParameterCurrency] = "\(currency)"
        } else {
            params[AnalyticsParameterCurrency] = "USD"
        }

        // Handle ecommerce property mapping
        for (propertyKey, value) in properties {
            if let firebaseKey = FirebaseUtils.ecommercePropertyMapping[propertyKey], !FirebaseUtils.isEmpty(value) {
                params[firebaseKey] = "\(value)"
            }
        }

        // Handle shipping and tax
        if let shipping = properties["shipping"], FirebaseUtils.isNumber(shipping) {
            params[AnalyticsParameterShipping] = FirebaseUtils.doubleValue(shipping)
        }

        if let tax = properties["tax"], FirebaseUtils.isNumber(tax) {
            params[AnalyticsParameterTax] = FirebaseUtils.doubleValue(tax)
        }

        // Handle order_id mapping to transaction_id
        if let orderId = properties["order_id"] {
            params[AnalyticsParameterTransactionID] = "\(orderId)"
            // Backward compatibility
            params["order_id"] = "\(orderId)"
        }
    }

    /**
     * Handles products array or root-level product properties
     */
    private func handleProducts(params: inout [String: Any], properties: [String: Any], isProductsArray: Bool) {
        var mappedProducts: [[String: Any]] = []

        if isProductsArray {
            // Handle products array
            if let products = properties["products"] as? [[String: Any]] {
                for product in products {
                    var productBundle: [String: Any] = [:]
                    putProductValue(params: &productBundle, properties: product)
                    if !productBundle.isEmpty {
                        mappedProducts.append(productBundle)
                    }
                }
            }
        } else {
            // Handle product at root level
            var productBundle: [String: Any] = [:]
            putProductValue(params: &productBundle, properties: properties)
            if !productBundle.isEmpty {
                mappedProducts.append(productBundle)
            }
        }

        if !mappedProducts.isEmpty {
            params[AnalyticsParameterItems] = mappedProducts
        }
    }

    /**
     * Maps product properties to Firebase parameters
     */
    private func putProductValue(params: inout [String: Any], properties: [String: Any]) {
        for (key, firebaseKey) in FirebaseUtils.productPropertiesMapping {
            guard let value = properties[key], !FirebaseUtils.isEmpty(value) else { continue }

            switch firebaseKey {
            case AnalyticsParameterItemID, AnalyticsParameterItemName, AnalyticsParameterItemCategory:
                params[firebaseKey] = "\(value)"
            case AnalyticsParameterQuantity:
                if FirebaseUtils.isNumber(value) {
                    params[firebaseKey] = FirebaseUtils.intValue(value)
                }
            case AnalyticsParameterPrice:
                if FirebaseUtils.isNumber(value) {
                    params[firebaseKey] = FirebaseUtils.doubleValue(value)
                }
            default:
                break
            }
        }
    }

    /**
     * Attaches all custom properties to Firebase parameters
     */
    private func attachAllCustomProperties(params: inout [String: Any], properties: [String: Any]?, isECommerceEvent: Bool) {
        guard let properties = properties, !properties.isEmpty else { return }

        for (key, value) in properties {
            let firebaseKey = FirebaseUtils.getTrimKey(key)

            // Skip reserved keywords for ecommerce events or empty values
            if (isECommerceEvent && FirebaseUtils.firebaseTrackReservedKeywords.contains(firebaseKey)) || FirebaseUtils.isEmpty(value) {
                continue
            }

            // Handle different value types
            if FirebaseUtils.isNumber(value) {
                params[firebaseKey] = FirebaseUtils.doubleValue(value)
            } else if let stringValue = value as? String {
                // Truncate strings longer than 100 characters
                let truncatedValue = stringValue.count > 100 ? String(stringValue.prefix(100)) : stringValue
                params[firebaseKey] = truncatedValue
            } else {
                let convertedString = "\(value)"
                // Only add if length is <= 100
                if convertedString.count <= 100 {
                    params[firebaseKey] = convertedString
                }
            }
        }
    }

}
