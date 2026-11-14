"""
Comprehensive unit and integration tests for Cross-Repository Dependency Guardian.
"""

import unittest
from pathlib import Path
from src.config import load_dependency_rules, find_matching_rules, matches_git_pattern
from src.java_parser import parse_java_source, compare_java_versions
from src.models import ChangedJavaFile, DependentTargetFile
from src.guardian import CrossRepoGuardian


class TestCrossRepoGuardian(unittest.TestCase):

    def test_git_pattern_matching(self):
        """Test recursive and direct glob patterns."""
        self.assertTrue(
            matches_git_pattern("src/main/java/com/example/dto/UserDTO.java", "**/dto/**/*.java")
        )
        self.assertTrue(
            matches_git_pattern("src/main/java/com/example/dto/UserDTO.java", "**/dto/*.java")
        )
        self.assertTrue(
            matches_git_pattern("src/main/java/com/example/dto/UserDTO.java", "**/*.java")
        )
        self.assertFalse(
            matches_git_pattern("src/main/java/com/example/controller/UserController.java", "**/dto/**/*.java")
        )

    def test_excel_rules_loading(self):
        """Test reading rules from repo_dependency_mapping.xlsx."""
        excel_path = Path(__file__).resolve().parent.parent / "repo_dependency_mapping.xlsx"
        rules = load_dependency_rules(excel_path)
        self.assertGreaterEqual(len(rules), 3)

        rule1 = rules[0]
        self.assertEqual(rule1.source_repo, "sample-org/order-service")
        self.assertEqual(rule1.target_repo, "sample-org/payment-service")
        self.assertEqual(rule1.dependency_type, "REST_API_CONSUMER")

        # Matching rules
        matched = find_matching_rules("sample-org/order-service", rules)
        self.assertGreaterEqual(len(matched), 1)

    def test_java_parser_and_delta(self):
        """Test AST parsing and delta computation between Java source versions."""
        old_code = """package com.acme.models;
public class Account {
    private String id;
    private Double balance;
    public Double getBalance() { return balance; }
    public void setBalance(Double balance) { this.balance = balance; }
}
"""
        new_code = """package com.acme.models;
import java.math.BigDecimal;
public class Account {
    private String id;
    // Type changed from Double to BigDecimal!
    private BigDecimal balance;
    public BigDecimal getBalance() { return balance; }
    public void setBalance(BigDecimal balance) { this.balance = balance; }
}
"""
        delta = compare_java_versions(old_code, new_code)
        self.assertEqual(delta["class_name"], "Account")
        self.assertEqual(len(delta["type_changed_fields"]), 1)
        self.assertEqual(delta["type_changed_fields"][0]["name"], "balance")
        self.assertEqual(delta["type_changed_fields"][0]["old_type"], "Double")
        self.assertEqual(delta["type_changed_fields"][0]["new_type"], "BigDecimal")

    def test_end_to_end_breaking_change_detection(self):
        """Test full orchestrator identifying breaking field and method changes."""
        guardian = CrossRepoGuardian()

        old_order_dto = """package com.example.orders.dto;
public class OrderDTO {
    private String trackingCode;
    public String getTrackingCode() { return trackingCode; }
}
"""
        new_order_dto = """package com.example.orders.dto;
public class OrderDTO {
    // trackingCode removed
    private String shipmentId;
    public String getShipmentId() { return shipmentId; }
}
"""
        payment_code = """package com.example.payment.consumer;
import com.example.orders.dto.OrderDTO;
public class PaymentClient {
    public void track(OrderDTO dto) {
        String code = dto.getTrackingCode();
    }
}
"""
        changed_source = [
            ChangedJavaFile(
                path="src/main/java/com/example/orders/dto/OrderDTO.java",
                status="modified",
                diff="""--- a/OrderDTO.java\n+++ b/OrderDTO.java\n- private String trackingCode;\n+ private String shipmentId;""",
                old_content=old_order_dto,
                new_content=new_order_dto,
            )
        ]
        target_files = [
            DependentTargetFile(
                repo="sample-org/payment-service",
                path="src/main/java/com/example/payment/consumer/PaymentClient.java",
                content=payment_code,
            )
        ]

        report = guardian.run_check(
            source_repo="sample-org/order-service",
            changed_files_override=changed_source,
            target_files_override=target_files,
        )

        self.assertTrue(report.has_breaking_changes)
        self.assertEqual(len(report.findings), 1)
        finding = report.findings[0]
        self.assertEqual(finding.target_repo, "sample-org/payment-service")
        self.assertIn("trackingCode", finding.breaking_change_summary)
        self.assertIn("CRITICAL", finding.severity)

    def test_repo_analyzer_integration(self):
        """Test RepoAnalyzer architecture extraction."""
        from src.repo_analyzer import RepoAnalyzer
        from src.github_client import GitHubClient

        client = GitHubClient()
        analyzer = RepoAnalyzer(client)
        summary = analyzer.analyze_repository("sample-org/order-service", role_hint="Service Provider")
        self.assertEqual(summary.repo_name, "sample-org/order-service")
        self.assertEqual(summary.role_in_contract, "Service Provider")
        self.assertIn("Spring Boot", summary.frameworks)

    def test_validation_annotation_tightening_with_line_numbers(self):
        """Test detecting added @NotNull / @NotBlank validation constraint along with line numbers."""
        guardian = CrossRepoGuardian()

        old_user_dto = """package com.example.dto;
public class UserDTO {
    private String email;
}
"""
        new_user_dto = """package com.example.dto;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.NotBlank;
public class UserDTO {
    @NotNull
    @NotBlank
    private String email;
}
"""
        target_code = """package com.example.client;
import com.example.dto.UserDTO;
public class RegistrationClient {
    public void register() {
        UserDTO dto = new UserDTO();
        dto.email = null;
    }
}
"""
        changed_source = [
            ChangedJavaFile(
                path="src/main/java/com/example/dto/UserDTO.java",
                status="modified",
                diff="""--- a/UserDTO.java\n+++ b/UserDTO.java\n+ @NotNull\n+ @NotBlank""",
                old_content=old_user_dto,
                new_content=new_user_dto,
            )
        ]
        target_files = [
            DependentTargetFile(
                repo="sample-org/payment-service",
                path="src/main/java/com/example/client/RegistrationClient.java",
                content=target_code,
            )
        ]

        report = guardian.run_check(
            source_repo="sample-org/order-service",
            changed_files_override=changed_source,
            target_files_override=target_files,
        )

        self.assertTrue(report.has_breaking_changes)
        self.assertGreaterEqual(len(report.findings), 1)
        finding = report.findings[0]
        self.assertIn("@NotNull", finding.breaking_change_summary)
        self.assertIsNotNone(finding.source_line)
        self.assertIsNotNone(finding.target_line)

    def test_jackson_json_property_mutation(self):
        """Test detecting changed @JsonProperty wire name with line numbers."""
        guardian = CrossRepoGuardian()

        old_order_dto = """package com.example.dto;
import com.fasterxml.jackson.annotation.JsonProperty;
public class OrderDTO {
    @JsonProperty("orderId")
    private String orderId;
}
"""
        new_order_dto = """package com.example.dto;
import com.fasterxml.jackson.annotation.JsonProperty;
public class OrderDTO {
    @JsonProperty("order_ref_id")
    private String orderId;
}
"""
        target_code = """package com.example.consumer;
public class OrderConsumer {
    private String orderId;
}
"""
        changed_source = [
            ChangedJavaFile(
                path="src/main/java/com/example/dto/OrderDTO.java",
                status="modified",
                diff="""--- a/OrderDTO.java\n+++ b/OrderDTO.java\n- @JsonProperty("orderId")\n+ @JsonProperty("order_ref_id")""",
                old_content=old_order_dto,
                new_content=new_order_dto,
            )
        ]
        target_files = [
            DependentTargetFile(
                repo="sample-org/payment-service",
                path="src/main/java/com/example/consumer/OrderConsumer.java",
                content=target_code,
            )
        ]

        report = guardian.run_check(
            source_repo="sample-org/order-service",
            changed_files_override=changed_source,
            target_files_override=target_files,
        )

        self.assertTrue(report.has_breaking_changes)
        finding = report.findings[0]
        self.assertIn("order_ref_id", finding.breaking_change_summary)
        self.assertIsNotNone(finding.source_line)


if __name__ == "__main__":
    unittest.main()
