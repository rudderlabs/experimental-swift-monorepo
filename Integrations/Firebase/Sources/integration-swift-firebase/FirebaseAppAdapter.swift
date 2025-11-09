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
    var isConfigured: Bool { get }
    func configure()
}

// MARK: Actual Implementation
class DefaultFirebaseAppAdapter: FirebaseAppAdapter {
    var isConfigured: Bool { FirebaseApp.app() != nil }
    
    func configure() {
        DispatchQueue.main.sync {
            FirebaseApp.configure()
        }
    }
}
