//
//  FirebaseAppAdapter.swift
//  integration-swift-firebase
//
//  Created by Vishal Gupta on 09/11/25.
//

import Foundation
import FirebaseCore

/**
 * Protocol to wrap FirebaseApp.
 */
protocol FirebaseAppAdapter {
    var firebaseAppInstance: Any? { get set }
    var isConfigured: Bool { get }
    
    func configure()
    func provideFirebaseAppInstance() -> Any?
}

// MARK: Actual Implementation
class DefaultFirebaseAppAdapter: FirebaseAppAdapter {
    var firebaseAppInstance: Any?
    var isConfigured: Bool { firebaseAppInstance != nil }

    func configure() {
        let setup = {
            FirebaseApp.configure()
            self.firebaseAppInstance = FirebaseApp.app()
        }
        Thread.isMainThread ? setup() : DispatchQueue.main.sync(execute: setup)
    }

    func provideFirebaseAppInstance() -> Any? {
        return FirebaseApp.app()
    }
}
