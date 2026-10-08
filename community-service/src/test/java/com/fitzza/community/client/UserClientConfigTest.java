package com.fitzza.community.client;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpsConfigurator;
import com.sun.net.httpserver.HttpsServer;
import java.io.InputStream;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyStore;
import java.util.concurrent.atomic.AtomicInteger;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManagerFactory;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.http.client.support.HttpRequestWrapper;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;

class UserClientConfigTest {

    @TempDir
    static Path certificates;

    private static SSLContext serverContext;
    private static SSLSocketFactory trustedSocketFactory;
    private SSLSocketFactory originalSocketFactory;
    private HttpsServer httpsServer;
    private HttpServer httpServer;
    private final AtomicInteger httpRequests = new AtomicInteger();
    private final AtomicInteger httpsRequests = new AtomicInteger();

    @BeforeAll
    static void createCertificate() throws Exception {
        Path keyStorePath = certificates.resolve("server.p12");
        Path keytoolLog = certificates.resolve("keytool.log");
        Process keytool = new ProcessBuilder(
                Path.of(System.getProperty("java.home"), "bin", "keytool").toString(),
                "-genkeypair", "-alias", "localhost", "-keyalg", "RSA", "-storetype", "PKCS12",
                "-keystore", keyStorePath.toString(), "-storepass", "test-password",
                "-dname", "CN=localhost", "-ext", "SAN=dns:localhost", "-validity", "1")
                .redirectErrorStream(true).redirectOutput(keytoolLog.toFile()).start();
        assertThat(keytool.waitFor()).as(Files.readString(keytoolLog)).isZero();
        KeyStore keys = KeyStore.getInstance("PKCS12");
        try (InputStream input = Files.newInputStream(keyStorePath)) {
            keys.load(input, "test-password".toCharArray());
        }
        KeyManagerFactory keyManagers = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
        keyManagers.init(keys, "test-password".toCharArray());
        serverContext = SSLContext.getInstance("TLS");
        serverContext.init(keyManagers.getKeyManagers(), null, null);

        // Match deployment: JKS certificate entries are readable without the integrity password.
        KeyStore trustStore = KeyStore.getInstance("JKS");
        trustStore.load(null, null);
        trustStore.setCertificateEntry("localhost", keys.getCertificate("localhost"));
        Path trustStorePath = certificates.resolve("truststore.jks");
        try (var output = Files.newOutputStream(trustStorePath)) {
            trustStore.store(output, "test-password".toCharArray());
        }
        try (InputStream input = Files.newInputStream(trustStorePath)) {
            trustStore.load(input, null);
        }
        TrustManagerFactory trustManagers = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        trustManagers.init(trustStore);
        SSLContext trustedContext = SSLContext.getInstance("TLS");
        trustedContext.init(null, trustManagers.getTrustManagers(), null);
        trustedSocketFactory = trustedContext.getSocketFactory();
    }

    @BeforeEach
    void startServers() throws Exception {
        originalSocketFactory = HttpsURLConnection.getDefaultSSLSocketFactory();
        httpServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        httpServer.createContext("/", exchange -> {
            httpRequests.incrementAndGet();
            exchange.sendResponseHeaders(200, -1);
            exchange.close();
        });
        httpServer.start();
        httpsServer = HttpsServer.create(new InetSocketAddress("localhost", 0), 0);
        httpsServer.setHttpsConfigurator(new HttpsConfigurator(serverContext));
        httpsServer.createContext("/", exchange -> {
            httpsRequests.incrementAndGet();
            if (exchange.getRequestURI().getPath().equals("/redirect")) {
                exchange.getResponseHeaders().add("Location", httpUrl());
                exchange.sendResponseHeaders(302, -1);
            } else {
                byte[] body = "[]".getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().add("Content-Type", "application/json");
                exchange.sendResponseHeaders(200, body.length);
                exchange.getResponseBody().write(body);
            }
            exchange.close();
        });
        httpsServer.start();
    }

    @AfterEach
    void stopServers() {
        HttpsURLConnection.setDefaultSSLSocketFactory(originalSocketFactory);
        httpsServer.stop(0);
        httpServer.stop(0);
    }

    @Test
    void acceptsTrustedCertificateWithMatchingHostname() {
        HttpsURLConnection.setDefaultSSLSocketFactory(trustedSocketFactory);
        assertThat(client().get().uri(httpsUrl()).retrieve().body(String.class)).isEqualTo("[]");
        assertThat(httpsRequests).hasValue(1);
    }

    @Test
    void rejectsUntrustedCertificate() {
        assertThatThrownBy(() -> client().get().uri(httpsUrl()).retrieve().body(String.class))
                .isInstanceOf(ResourceAccessException.class)
                .hasMessageContaining("PKIX");
        assertThat(httpsRequests).hasValue(0);
    }

    @Test
    void rejectsCertificateForDifferentHostname() {
        HttpsURLConnection.setDefaultSSLSocketFactory(trustedSocketFactory);
        assertThatThrownBy(() -> client().get().uri(httpsUrl().replace("localhost", "127.0.0.1"))
                .retrieve().body(String.class))
                .isInstanceOf(ResourceAccessException.class)
                .hasMessageContaining("subject alternative");
        assertThat(httpsRequests).hasValue(0);
    }

    @Test
    void rejectsHttpDestinationAfterServiceDiscovery() {
        RestClient client = new UserClientConfig().loadBalancedRestClientBuilder()
                .requestInterceptor((request, body, execution) -> execution.execute(new HttpRequestWrapper(request) {
                    @Override
                    public URI getURI() {
                        return URI.create(httpUrl());
                    }
                }, body)).build();
        assertThatThrownBy(() -> client.get().uri("https://user-service/internal/users")
                .header(UserServiceClient.INTERNAL_TOKEN_HEADER, "test-token").retrieve().body(String.class))
                .isInstanceOf(ResourceAccessException.class)
                .hasMessageContaining("require HTTPS");
        assertThat(httpRequests).hasValue(0);
    }

    @Test
    void doesNotFollowRedirectToHttp() {
        HttpsURLConnection.setDefaultSSLSocketFactory(trustedSocketFactory);
        assertThat(client().get().uri(httpsUrl() + "/redirect")
                .header(UserServiceClient.INTERNAL_TOKEN_HEADER, "test-token")
                .retrieve().toBodilessEntity().getStatusCode().value()).isEqualTo(302);
        assertThat(httpRequests).hasValue(0);
    }

    private RestClient client() {
        return new UserClientConfig().loadBalancedRestClientBuilder().build();
    }

    private String httpsUrl() {
        return "https://localhost:" + httpsServer.getAddress().getPort();
    }

    private String httpUrl() {
        return "http://localhost:" + httpServer.getAddress().getPort();
    }
}
