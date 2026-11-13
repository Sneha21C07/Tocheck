"""
Main CLI and GitHub Actions runner for Cross-Repository Java Dependency Guardian.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from src.guardian import CrossRepoGuardian
from src.models import ChangedJavaFile, DependentTargetFile


def parse_github_event():
    """Extract event details if running inside GitHub Actions environment."""
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if not event_path or not os.path.exists(event_path):
        return None, None

    try:
        with open(event_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pr_number = data.get("pull_request", {}).get("number")
        commit_sha = data.get("after") or data.get("head_commit", {}).get("id")
        return pr_number, commit_sha
    except Exception as e:
        print(f"Warning: Failed to parse GITHUB_EVENT_PATH: {e}")
        return None, None


def run_demo_simulation(guardian: CrossRepoGuardian):
    """
    Simulates a real-world scenario:
    OrderService (Repo A) deletes a field `customerId` and changes `orderId` type from Long to UUID.
    PaymentService (Repo B) consumes OrderDTO and calls `order.getCustomerId()` and `order.getOrderId()`.
    """
    print("\n" + "=" * 80)
    print("RUNNING CROSS-REPO GUARDIAN SIMULATION DEMO")
    print("=" * 80 + "\n")

    source_repo = "sample-org/order-service"
    target_repo = "sample-org/payment-service"

    old_order_dto = """package com.example.orders.dto;

import java.math.BigDecimal;

public class OrderDTO {
    private Long orderId;
    private String customerId;
    private BigDecimal amount;
    private String status;

    public Long getOrderId() { return orderId; }
    public void setOrderId(Long orderId) { this.orderId = orderId; }
    public String getCustomerId() { return customerId; }
    public void setCustomerId(String customerId) { this.customerId = customerId; }
    public BigDecimal getAmount() { return amount; }
    public void setAmount(BigDecimal amount) { this.amount = amount; }
}
"""

    new_order_dto = """package com.example.orders.dto;

import java.math.BigDecimal;
import java.util.UUID;

public class OrderDTO {
    // BREAKING: orderId changed from Long to UUID!
    private UUID orderId;
    // BREAKING: customerId field removed! Replaced by accountRef
    private String accountRef;
    private BigDecimal amount;
    private String status;

    public UUID getOrderId() { return orderId; }
    public void setOrderId(UUID orderId) { this.orderId = orderId; }
    public String getAccountRef() { return accountRef; }
    public void setAccountRef(String accountRef) { this.accountRef = accountRef; }
    public BigDecimal getAmount() { return amount; }
    public void setAmount(BigDecimal amount) { this.amount = amount; }
}
"""

    git_diff = """--- a/src/main/java/com/example/orders/dto/OrderDTO.java
+++ b/src/main/java/com/example/orders/dto/OrderDTO.java
@@ -6,2 +6,2 @@ public class OrderDTO {
-    private Long orderId;
-    private String customerId;
+    private UUID orderId;
+    private String accountRef;
"""

    payment_consumer_code = """package com.example.payment.consumer;

import com.example.orders.dto.OrderDTO;
import org.springframework.stereotype.Service;

@Service
public class PaymentProcessingService {

    public void processPayment(OrderDTO order) {
        Long id = order.getOrderId(); // WILL BREAK: Type mismatch (UUID vs Long)
        String customer = order.getCustomerId(); // WILL BREAK: Method getCustomerId() deleted!
        System.out.println("Processing payment for customer: " + customer + ", order: " + id);
    }
}
"""

    changed_source_files = [
        ChangedJavaFile(
            path="src/main/java/com/example/orders/dto/OrderDTO.java",
            status="modified",
            diff=git_diff,
            old_content=old_order_dto,
            new_content=new_order_dto,
        )
    ]

    target_files = [
        DependentTargetFile(
            repo=target_repo,
            path="src/main/java/com/example/payment/consumer/PaymentProcessingService.java",
            content=payment_consumer_code,
        )
    ]

    report = guardian.run_check(
        source_repo=source_repo,
        changed_files_override=changed_source_files,
        target_files_override=target_files,
    )

    print(report.markdown_summary)
    print("\n" + "=" * 80)
    print(f"Analysis Complete. Impact Detected: {report.has_breaking_changes}")
    print("=" * 80 + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description="Cross-Repository Java Dependency Guardian")
    parser.add_argument("--repo", help="Source repository (e.g., owner/repo)")
    parser.add_argument("--pr", type=int, help="Pull Request number")
    parser.add_argument("--commit", help="Commit SHA for push events")
    parser.add_argument("--excel", help="Path to repo_dependency_mapping.xlsx")
    parser.add_argument("--simulate-demo", action="store_true", help="Run offline simulation demo")
    parser.add_argument("--fail-on-breaking", action="store_true", help="Exit with 1 if breaking changes detected")

    args = parser.parse_args()

    excel_file = Path(args.excel) if args.excel else Path("repo_dependency_mapping.xlsx")
    guardian = CrossRepoGuardian(excel_path=str(excel_file))

    if args.simulate_demo:
        report = run_demo_simulation(guardian)
        if args.fail_on_breaking and report.has_breaking_changes:
            sys.exit(1)
        sys.exit(0)

    # Resolve Repo and PR / Commit from arguments or GitHub Actions environment
    source_repo = args.repo or os.getenv("GITHUB_REPOSITORY")
    pr_number = args.pr
    commit_sha = args.commit

    if not pr_number and not commit_sha:
        event_pr, event_commit = parse_github_event()
        pr_number = pr_number or event_pr
        commit_sha = commit_sha or event_commit

    if not source_repo:
        print("Error: Source repository not specified. Provide --repo or run in GitHub Actions.")
        sys.exit(1)

    report = guardian.run_check(
        source_repo=source_repo,
        pr_number=pr_number,
        commit_sha=commit_sha,
    )

    print(report.markdown_summary)

    if args.fail_on_breaking and report.has_breaking_changes:
        print("Failing CI build because cross-repository breaking changes were detected.")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
