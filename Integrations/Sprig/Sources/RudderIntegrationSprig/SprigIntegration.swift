import Foundation
import UIKit
import RudderStackAnalytics

public class SprigIntegration: IntegrationPlugin, StandardIntegration {

    public var pluginType: PluginType = .terminal
    public var analytics: Analytics?
    public var key: String = "Sprig"

    final var sprigAdapter: SprigAdapter
    private weak var viewController: UIViewController?
    private var loggingListenerRegistered = false

    init(sprigAdapter: SprigAdapter) {
        self.sprigAdapter = sprigAdapter
    }

    public convenience init() {
        self.init(sprigAdapter: DefaultSprigAdapter())
    }

    // MARK: - Public API

    /// Sets the view controller Sprig will present in-app surveys from.
    ///
    /// ## When to call
    /// Set the view controller when it becomes the active presentation context — typically from
    /// `viewDidAppear(_:)` of the topmost view controller in your app. You can clear it explicitly
    /// from `viewWillDisappear(_:)` by passing `nil`, but this is optional (see "Lifetime" below).
    ///
    /// ## Lifetime
    /// The reference is held **weakly**, so the integration will never keep your view controller
    /// alive past its natural lifetime. When the host releases its own reference, the stored
    /// reference auto-clears and subsequent `track` calls fall back to plain `Sprig.track(...)`
    /// (i.e. no survey is presented).
    ///
    /// ## Presentation safety
    /// On a `track` event:
    /// - If no view controller is set, the integration calls plain `Sprig.track(...)` on the
    ///   caller's thread.
    /// - If a view controller is set, the integration hops to the main thread (so it is safe to
    ///   call `track` from any thread), verifies the view controller is still presentable —
    ///   loaded, attached to a window, and not being dismissed — and either calls
    ///   `Sprig.trackAndPresent(...)` or falls back to plain `Sprig.track(...)` if it is not.
    ///   No exception is thrown; the event is still delivered.
    ///
    /// - Parameter viewController: The view controller to present surveys from, or `nil` to clear.
    public func setViewController(_ viewController: UIViewController?) {
        self.viewController = viewController
    }

    // MARK: - IntegrationPlugin

    public func getDestinationInstance() -> Any? {
        return sprigAdapter.sprigInstance
    }

    public func create(destinationConfig: [String: Any]) throws {
        guard sprigAdapter.sprigInstance == nil else { return }
        guard let environmentId = destinationConfig["environmentId"] as? String, !environmentId.isEmpty else {
            LoggerAnalytics.error("SprigIntegration: Invalid or missing environmentId. Aborting Sprig initialization.")
            return
        }
        sprigAdapter.sprigInstance = sprigAdapter.provideSprigInstance()
        sprigAdapter.configure(withEnvironment: environmentId)
        registerSprigLogging()
        LoggerAnalytics.debug("SprigIntegration: Sprig SDK initialized successfully.")
    }

    public func reset() {
        sprigAdapter.logout()
        LoggerAnalytics.debug("SprigIntegration: Sprig logout called.")
    }

    public func teardown() {
        if loggingListenerRegistered {
            sprigAdapter.unregisterLoggingListener()
            loggingListenerRegistered = false
        }
        viewController = nil
        sprigAdapter.sprigInstance = nil
        LoggerAnalytics.debug("SprigIntegration: teardown completed.")
    }

    // MARK: - EventPlugin

    public func identify(payload: IdentifyEvent) {
        guard let userId = payload.userId, !userId.isEmpty else {
            LoggerAnalytics.error("SprigIntegration: UserId is not set. Dropping identify event.")
            return
        }
        sprigAdapter.setUserIdentifier(userId)

        if let traits = payload.context?["traits"] as? AnyCodable,
           let traitsDictionary = traits.value as? [String: Any] {
            SprigUtils.setSprigAttributes(traitsDictionary, adapter: sprigAdapter)
        }

        LoggerAnalytics.debug("SprigIntegration: Identify event processed for userId: \(userId)")
    }

    public func track(payload: TrackEvent) {
        let eventName = payload.event
        let properties = payload.properties?.dictionary?.rawDictionary

        guard let viewController = self.viewController else {
            sprigAdapter.track(eventName: eventName, properties: properties)
            LoggerAnalytics.debug("SprigIntegration: track called for event '\(eventName)'")
            return
        }

        SprigUtils.runOnMain { [weak self] in
            guard let self = self else { return }
            if SprigUtils.isPresentable(viewController) {
                self.sprigAdapter.trackAndPresent(eventName: eventName, properties: properties, from: viewController)
                LoggerAnalytics.debug("SprigIntegration: trackAndPresent called for event '\(eventName)'")
            } else {
                self.sprigAdapter.track(eventName: eventName, properties: properties)
                LoggerAnalytics.debug("SprigIntegration: track called for event '\(eventName)'")
            }
        }
    }

    // MARK: - Helpers

    /// Forwards Sprig SDK log messages to the Rudder logger.
    ///
    /// Sprig iOS emits log output via `.loggingEvent` lifecycle callbacks but — unlike Sprig
    /// Android — does not expose a severity with each message, so every message is forwarded
    /// at `verbose`. Sprig output therefore only surfaces when the Rudder log level is set to
    /// `.verbose`. Registration is skipped entirely when the Rudder log level is `.none`.
    private func registerSprigLogging() {
        guard LoggerAnalytics.logLevel != .none else { return }

        sprigAdapter.registerLoggingListener { message in
            LoggerAnalytics.verbose("SprigIntegration: \(message)")
        }
        loggingListenerRegistered = true
    }

}
