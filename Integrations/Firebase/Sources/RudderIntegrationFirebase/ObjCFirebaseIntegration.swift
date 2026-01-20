//
//  ObjCFirebaseIntegration.swift
//  RudderIntegrationFirebase
//
//  Created by Satheesh Kannan on 11/01/26.
//

import Foundation
import RudderStackAnalytics

// MARK: - ObjCFirebaseIntegration
/**
 An Objective-C compatible wrapper for the Firebase Integration.

 This class provides an Objective-C interface to the Firebase integration,
 allowing Objective-C apps to use the Firebase device mode integration with RudderStack.

 ## Usage in Objective-C:
 ```objc
 RSSConfigurationBuilder *builder = [[RSSConfigurationBuilder alloc] initWithWriteKey:@"<WriteKey>"
                                                          dataPlaneUrl:@"<DataPlaneUrl>"];
 RSSAnalytics *analytics = [[RSSAnalytics alloc] initWithConfiguration:[builder build]];

 RSSFirebaseIntegration *firebaseIntegration = [[RSSFirebaseIntegration alloc] init];
 [analytics addPlugin:firebaseIntegration];
 ```
 */
@objc(RSSFirebaseIntegration)
public class ObjCFirebaseIntegration: NSObject, ObjCIntegrationPlugin, ObjCStandardIntegration {

    // MARK: - ObjCPlugin Properties

    public var pluginType: PluginType {
        get { firebaseIntegration.pluginType }
        set { firebaseIntegration.pluginType = newValue }
    }

    // MARK: - ObjCIntegrationPlugin Properties

    public var key: String {
        get { firebaseIntegration.key }
        set { firebaseIntegration.key = newValue }
    }

    // MARK: - Private Properties

    private let firebaseIntegration: FirebaseIntegration

    // MARK: - Initializers

    /**
     Initializes a new Firebase integration instance.

     Use this initializer to create a Firebase integration that can be added to the analytics client.
     */
    @objc
    public override init() {
        self.firebaseIntegration = FirebaseIntegration()
        super.init()
    }

    // MARK: - ObjCIntegrationPlugin Methods

    /**
     Returns the Firebase Analytics instance.

     - Returns: The Firebase Analytics instance, or nil if not initialized.
     */
    @objc
    public func getDestinationInstance() -> Any? {
        return firebaseIntegration.getDestinationInstance()
    }

    /**
     Creates and configures the Firebase SDK with the provided destination configuration.

     - Parameters:
        - destinationConfig: Configuration dictionary from RudderStack dashboard.
        - errorPointer: A pointer to an NSError that will be set if initialization fails.
     - Returns: `true` if initialization succeeded, `false` otherwise.
     */
    @objc
    public func createWithDestinationConfig(_ destinationConfig: [String: Any], error errorPointer: NSErrorPointer) -> Bool {
        do {
            try firebaseIntegration.create(destinationConfig: destinationConfig)
            return true
        } catch let err as NSError {
            errorPointer?.pointee = err
            return false
        } catch {
            errorPointer?.pointee = NSError(
                domain: "com.rudderstack.FirebaseIntegration",
                code: -1,
                userInfo: [NSLocalizedDescriptionKey: error.localizedDescription]
            )
            return false
        }
    }

    // MARK: - ObjCEventPlugin Methods

    /**
     Processes an identify event and forwards it to the underlying Firebase integration.

     - Parameter payload: The ObjC identify event payload.
     */
    @objc
    public func identify(_ payload: ObjCIdentifyEvent) {
        var identifyEvent = IdentifyEvent(options: payload.options)
        identifyEvent.anonymousId = payload.anonymousId
        identifyEvent.userId = payload.userId
        identifyEvent.context = payload.context?.codableWrapped

        firebaseIntegration.identify(payload: identifyEvent)
    }
    
    /**
     Processes a track event and forwards it to the underlying Firebase integration.

     - Parameter payload: The ObjC track event payload.
     */
    @objc
    public func track(_ payload: ObjCTrackEvent) {
        var trackEvent = TrackEvent(
            event: payload.eventName,
            properties: payload.properties,
            options: payload.options
        )
        trackEvent.anonymousId = payload.anonymousId
        trackEvent.userId = payload.userId

        firebaseIntegration.track(payload: trackEvent)
    }

    /**
     Processes a screen event and forwards it to the underlying Firebase integration.

     - Parameter payload: The ObjC screen event payload.
     */
    @objc
    public func screen(_ payload: ObjCScreenEvent) {
        var screenEvent = ScreenEvent(
            screenName: payload.screenName,
            category: payload.category,
            properties: payload.properties,
            options: payload.options
        )
        screenEvent.anonymousId = payload.anonymousId
        screenEvent.userId = payload.userId

        firebaseIntegration.screen(payload: screenEvent)
    }
    
    /**
     Resets the integration state.

     This clears the Firebase user ID.
     */
    @objc
    public func reset() {
        firebaseIntegration.reset()
    }
}
