package com.example.query.dto;

import java.io.Serializable;
import java.util.List;
//after change
public class UserDTO implements Serializable {
    private String userId;
    private String name;
    private String email;
    // BREAKING CHANGE FOR THIS COMMIT: department renamed to deptCode
    private String deptCode;
    private String userRole;
    private String region;
    private String status;
    private List<String> skills;

    public UserDTO() {}

    public String getUserId() { return userId; }
    public void setUserId(String userId) { this.userId = userId; }

    public String getName() { return name; }
    public void setName(String name) { this.name = name; }

    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }

    public String getDeptCode() { return deptCode; }
    public void setDeptCode(String deptCode) { this.deptCode = deptCode; }

    public String getUserRole() { return userRole; }
    public void setUserRole(String userRole) { this.userRole = userRole; }

    public String getRegion() { return region; }
    public void setRegion(String region) { this.region = region; }

    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }

    public List<String> getSkills() { return skills; }
    public void setSkills(List<String> skills) { this.skills = skills; }
}
