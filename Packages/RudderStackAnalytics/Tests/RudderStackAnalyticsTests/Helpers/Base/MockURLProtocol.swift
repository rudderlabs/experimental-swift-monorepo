//
//  MockURLProtocol.swift
//  RudderStackAnalyticsTests
//
//  Created by Satheesh Kannan on 22/08/25.
//

import Foundation

/**
 A `URLProtocol` subclass for mocking HTTP responses in tests.
 */
final class MockURLProtocol: URLProtocol {
    
    /**
     Closure the test sets to provide a mocked response.
     - Returns: `(statusCode, responseData, headers)`
     */
    static var requestHandler: ((URLRequest) throws -> (Int, Data?, [String: String]?))?
    
    /**
     When `false` (default), GET requests return 200 empty even if `requestHandler` is set.
     This absorbs background source config downloads spawned by `Analytics` initialization.
     Tests that need GET requests to reach the handler (e.g. SourceConfigProviderTests)
     must set this to `true`.
     */
    static var forwardGetRequestsToHandler = false
    
    // MARK: - URLProtocol overrides
    
    override class func canInit(with request: URLRequest) -> Bool {
        // Intercept all requests
        return true
    }
    
    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }
    
    override func startLoading() {
        // GET requests return 200 empty unless the test explicitly opts in.
        // This absorbs background source config downloads (GET /sourceConfig)
        // that Analytics initialization spawns asynchronously, preventing them from
        // going through the test's handler and corrupting callCount/attemptCount.
        //
        // POST requests with no handler stay pending — no success (batches not deleted)
        // and no failure (no retry loop).
        if request.httpMethod == "GET" &&
            (MockURLProtocol.requestHandler == nil || !MockURLProtocol.forwardGetRequestsToHandler) {
            if let url = request.url,
               let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: nil) {
                client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
                client?.urlProtocolDidFinishLoading(self)
            }
            return
        }
        
        guard let handler = MockURLProtocol.requestHandler else {
            // POST with no handler: keep pending
            return
        }
        
        do {
            let (statusCode, data, headers) = try handler(request)
            
            guard let url = request.url else {
                client?.urlProtocol(self, didFailWithError: URLError(.badURL))
                return
            }
            
            // Safely build HTTPURLResponse
            if let response = HTTPURLResponse(
                url: url,
                statusCode: statusCode,
                httpVersion: "HTTP/1.1",
                headerFields: headers
            ) {
                client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            } else {
                client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
                return
            }
            
            // Send body if available
            if let data = data {
                client?.urlProtocol(self, didLoad: data)
            }
            
            client?.urlProtocolDidFinishLoading(self)
            
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }
    
    override func stopLoading() {
        /* Default implementation (no-op) */
    }
}

// MARK: - Per-test request scoping

extension MockURLProtocol {

    /**
     Installs `handler` for requests sent by the `Analytics` instance configured with `writeKey` only.

     `requestHandler` is global, and `Analytics` instances left over from earlier tests can still send requests
     (retries, flushes, source config downloads). Those requests carry a different write key; they get an empty
     `200` here so they can neither reach the running test's handler nor skew its counts.
     */
    static func handleRequests(
        sentWith writeKey: String,
        _ handler: @escaping (URLRequest) throws -> (Int, Data?, [String: String]?)
    ) {
        let authorization = "Basic " + Data((writeKey + ":").utf8).base64EncodedString()
        let ignoredRequestStatusCode = 200
        requestHandler = { request in
            guard request.value(forHTTPHeaderField: "Authorization") == authorization else {
                return (ignoredRequestStatusCode, nil, nil)
            }
            return try handler(request)
        }
    }
}

// MARK: - RequestCounter

/**
 A thread-safe counter for requests seen by a `MockURLProtocol` handler, which runs on `URLSession`'s queue.
 */
final class RequestCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0

    var value: Int {
        lock.lock()
        defer { lock.unlock() }
        return count
    }

    /// Increments the count and returns the new value.
    @discardableResult
    func increment() -> Int {
        lock.lock()
        defer { lock.unlock() }
        count += 1
        return count
    }
}
