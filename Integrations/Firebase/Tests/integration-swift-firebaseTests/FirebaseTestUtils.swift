//
//  FirebaseTestUtils.swift
//  integration-swift-firebase
//
//  Created by Vishal Gupta on 09/11/25.
//

@testable import integration_swift_firebase

/**
 * Mock Adapter for FirebaseApp
 */
class MockFirebaseAppAdapter: FirebaseAppAdapter {
    var configured = false

    var isConfigured: Bool { configured }

    func configure() {
        configured = true
    }
}
