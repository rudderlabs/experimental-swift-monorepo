import Foundation
import UIKit
import RudderStackAnalytics

@objc(RSSSprigIntegration)
public class ObjCSprigIntegration: NSObject, ObjCIntegrationPlugin, ObjCStandardIntegration {

    // MARK: - ObjCPlugin Properties

    public var pluginType: PluginType {
        get { sprigIntegration.pluginType }
        set { sprigIntegration.pluginType = newValue }
    }

    // MARK: - ObjCIntegrationPlugin Properties

    public var key: String {
        get { sprigIntegration.key }
        set { sprigIntegration.key = newValue }
    }

    // MARK: - Private Properties

    private let sprigIntegration: SprigIntegration

    // MARK: - Initializers

    @objc
    public override init() {
        self.sprigIntegration = SprigIntegration()
        super.init()
    }

    // MARK: - Public API

    /// Sets the view controller Sprig will present in-app surveys from.
    ///
    /// ## When to call
    /// Set the view controller when it becomes the active presentation context — typically from
    /// `-viewDidAppear:` of the topmost view controller in your app. You can clear it explicitly
    /// from `-viewWillDisappear:` by passing `nil`, but this is optional (see "Lifetime" below).
    ///
    /// ## Lifetime
    /// The reference is held **weakly**, so the integration will never keep your view controller
    /// alive past its natural lifetime. When the host releases its own reference, the stored
    /// reference auto-clears and subsequent `track` calls fall back to plain `[Sprig track:]`
    /// (i.e. no survey is presented).
    ///
    /// ## Presentation safety
    /// On a `track` event:
    /// - If no view controller is set, the integration calls plain `[Sprig track:]` on the
    ///   caller's thread.
    /// - If a view controller is set, the integration hops to the main thread (so it is safe to
    ///   call `track` from any thread), verifies the view controller is still presentable —
    ///   loaded, attached to a window, and not being dismissed — and either calls
    ///   `[Sprig trackAndPresent:from:]` or falls back to plain `[Sprig track:]` if it is not.
    ///   The event is still delivered.
    ///
    /// - Parameter viewController: The view controller to present surveys from, or `nil` to clear.
    @objc
    public func setViewController(_ viewController: UIViewController?) {
        sprigIntegration.setViewController(viewController)
    }

    // MARK: - ObjCIntegrationPlugin Methods

    @objc
    public func getDestinationInstance() -> Any? {
        return sprigIntegration.getDestinationInstance()
    }

    @objc
    public func createWithDestinationConfig(_ destinationConfig: [String: Any], error errorPointer: NSErrorPointer) -> Bool {
        do {
            try sprigIntegration.create(destinationConfig: destinationConfig)
            return true
        } catch let err as NSError {
            errorPointer?.pointee = err
            return false
        } catch {
            errorPointer?.pointee = NSError(
                domain: "com.rudderstack.SprigIntegration",
                code: -1,
                userInfo: [NSLocalizedDescriptionKey: error.localizedDescription]
            )
            return false
        }
    }

    // MARK: - ObjCEventPlugin Methods

    @objc
    public func identify(_ payload: ObjCIdentifyEvent) {
        var identifyEvent = IdentifyEvent(options: payload.options)
        identifyEvent.anonymousId = payload.anonymousId
        identifyEvent.userId = payload.userId
        identifyEvent.context = payload.context?.codableWrapped

        sprigIntegration.identify(payload: identifyEvent)
    }

    @objc
    public func track(_ payload: ObjCTrackEvent) {
        var trackEvent = TrackEvent(
            event: payload.eventName,
            properties: payload.properties,
            options: payload.options
        )
        trackEvent.anonymousId = payload.anonymousId
        trackEvent.userId = payload.userId

        sprigIntegration.track(payload: trackEvent)
    }

    @objc
    public func reset() {
        sprigIntegration.reset()
    }
}
