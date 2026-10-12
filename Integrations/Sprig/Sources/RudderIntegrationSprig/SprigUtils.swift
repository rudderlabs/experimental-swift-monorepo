import Foundation
import UIKit
import RudderStackAnalytics

enum SprigUtils {
    static let emailKey = "email"

    /// Maximum length (in characters) accepted by Sprig for a visitor-attribute key.
    /// Keys longer than this are trimmed to fit.
    static let maxAttributeKeyLength = 255

    /// Trait keys handled by dedicated Sprig setters (e.g. `setEmailAddress`) rather than the
    /// generic `setVisitorAttribute`. Keys listed here are skipped by the custom-trait loop so
    /// they are not also sent as visitor attributes.
    static let standardTraitKeys: Set<String> = [emailKey]

    static func setSprigAttributes(_ traits: [String: Any], adapter: SprigAdapter) {
        setStandardTraits(traits, adapter: adapter)
        setCustomTraits(traits, adapter: adapter)
    }

    private static func setStandardTraits(_ traits: [String: Any], adapter: SprigAdapter) {
        if let email = traits[emailKey] as? String {
            adapter.setEmailAddress(email)
        }
    }

    private static func setCustomTraits(_ traits: [String: Any], adapter: SprigAdapter) {
        for (key, value) in traits where !standardTraitKeys.contains(key) {
            setVisitorAttribute(key: key, value: value, adapter: adapter)
        }
    }

    private static func setVisitorAttribute(key: String, value: Any, adapter: SprigAdapter) {
        if key.hasPrefix("!") {
            LoggerAnalytics.warn("SprigIntegration: '\(key)' is not a valid property name. Property names cannot start with '!'. Ignoring property.")
            return
        }
        let normalizedKey = normalizeKeyLength(key)
        guard isSupportedValue(value) else {
            LoggerAnalytics.warn("SprigIntegration: '\(value)' is not a valid property value. Only String, Bool, Double and Int are accepted. Ignoring property.")
            return
        }
        adapter.setVisitorAttribute(key: normalizedKey, value: value)
    }

    /// Sprig accepts String, Bool, Int, and Double. Swift bridges Bool/Int/Double to NSNumber,
    /// so a single `is NSNumber` check covers all numeric/boolean inputs (including ObjC values).
    private static func isSupportedValue(_ value: Any) -> Bool {
        return value is String || value is NSNumber
    }

    private static func normalizeKeyLength(_ key: String) -> String {
        guard key.count > maxAttributeKeyLength else { return key }
        let trimmed = String(key.prefix(maxAttributeKeyLength))
        LoggerAnalytics.warn("SprigIntegration: property name '\(key)' exceeds \(maxAttributeKeyLength) characters. Trimming to '\(trimmed)'.")
        return trimmed
    }

    static func runOnMain(_ block: @escaping () -> Void) {
        if Thread.isMainThread {
            block()
        } else {
            DispatchQueue.main.async(execute: block)
        }
    }

    static func isPresentable(_ viewController: UIViewController) -> Bool {
        return viewController.isViewLoaded
            && viewController.view.window != nil
            && !viewController.isBeingDismissed
    }
}
