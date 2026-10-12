//
//  ContentView.swift
//  SprigExample
//
//  Created by Vishal Gupta on 25/04/26.
//

import SwiftUI
import UIKit
import RudderIntegrationSprig

struct ContentView: View {
    private var analyticsManager = AnalyticsManager.shared

    var body: some View {
        NavigationView {
            ScrollView {
                VStack(spacing: 16) {
                    userIdentitySection
                    trackEventsSection
                    resetSection
                }
                .padding()
            }
            .navigationTitle("Sprig Example")
        }
        // Sprig SDK requires a UIViewController to present in-app surveys.
        // Hand the topmost view controller to the integration once the UI is on screen.
        .background(ViewControllerProvider { viewController in
            AnalyticsManager.shared.sprigIntegration?.setViewController(viewController)
        })
    }
}

extension ContentView {

    var userIdentitySection: some View {
        VStack(spacing: 12) {
            Text("User Identity")
                .font(.headline)

            Button("Identify User (Simple)") {
                analyticsManager.identifyUserSimple()
            }
            .buttonStyle(PrimaryButtonStyle())

            Button("Identify User (With Traits)") {
                analyticsManager.identifyUser()
            }
            .buttonStyle(PrimaryButtonStyle())
        }
        .padding()
        .background(Color.gray.opacity(0.1))
        .cornerRadius(10)
    }

    var trackEventsSection: some View {
        VStack(spacing: 12) {
            Text("Track Events")
                .font(.headline)

            Button("Track (No Properties)") {
                analyticsManager.trackWithoutProperties()
            }
            .buttonStyle(SecondaryButtonStyle())

            Button("Track (With Properties)") {
                analyticsManager.trackWithProperties()
            }
            .buttonStyle(SecondaryButtonStyle())
        }
        .padding()
        .background(Color.blue.opacity(0.1))
        .cornerRadius(10)
    }

    var resetSection: some View {
        VStack(spacing: 12) {
            Text("Reset")
                .font(.headline)

            Button("Reset") {
                analyticsManager.reset()
            }
            .buttonStyle(PrimaryButtonStyle())
        }
        .padding()
        .background(Color.red.opacity(0.1))
        .cornerRadius(10)
    }
}

// MARK: - View Controller Provider

/// Bridges SwiftUI to UIKit so the Sprig integration can be handed the
/// topmost view controller for in-app survey presentation.
private struct ViewControllerProvider: UIViewControllerRepresentable {
    let onResolve: (UIViewController) -> Void

    func makeUIViewController(context: Context) -> ResolverViewController {
        ResolverViewController(onResolve: onResolve)
    }

    func updateUIViewController(_ uiViewController: ResolverViewController, context: Context) {}

    final class ResolverViewController: UIViewController {
        let onResolve: (UIViewController) -> Void

        init(onResolve: @escaping (UIViewController) -> Void) {
            self.onResolve = onResolve
            super.init(nibName: nil, bundle: nil)
        }

        required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

        override func viewDidAppear(_ animated: Bool) {
            super.viewDidAppear(animated)
            // Walk up to the topmost presented controller so Sprig can present from it.
            let host = topMostViewController(from: self) ?? self
            onResolve(host)
        }

        private func topMostViewController(from viewController: UIViewController) -> UIViewController? {
            var current: UIViewController? = viewController.view.window?.rootViewController ?? viewController
            while let presented = current?.presentedViewController {
                current = presented
            }
            return current
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
