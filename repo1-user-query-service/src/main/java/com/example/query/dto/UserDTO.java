package com.example.query.dto;

import java.io.Serializable;
import java.util.List;

public class UserDTO implements Serializable {
    // BREAKING CHANGE: userId removed and renamed to accountId!
    // repo2 (Sneha21C07/tocheck2) invokes getUserId() and will break!
    private String accountId;
    private String name;
    private String email;
    // BREAKING CHANGE: department field renamed to departmentCode!
    private String departmentCode;
    private String role;
    private String region;
    // BREAKING CHANGE: status field renamed to accountStatus!
    private String accountStatus;
    private List<String> skills;

    public UserDTO() {}

    public String getAccountId() { return accountId; }
    public void setAccountId(String accountId) { this.accountId = accountId; }

    public String getName() { return name; }
    public void setName(String name) { this.name = name; }

    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }

    public String getDepartmentCode() { return departmentCode; }
    public void setDepartmentCode(String departmentCode) { this.departmentCode = departmentCode; }

    public String getRole() { return role; }
    public void setRole(String role) { this.role = role; }

    public String getRegion() { return region; }
    public void setRegion(String region) { this.region = region; }

    public String getAccountStatus() { return accountStatus; }
    public void setAccountStatus(String accountStatus) { this.accountStatus = accountStatus; }

    public List<String> getSkills() { return skills; }
    public void setSkills(List<String> skills) { this.skills = skills; }
}

// Test trigger
