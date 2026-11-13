package com.example.query.controller;

import com.example.query.dto.UserDTO;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/users")
public class UserQueryController {

    @GetMapping
    public ResponseEntity<UserDTO> getUser(
            @RequestParam("userId") String userId,
            @RequestParam("department") String department) {
        UserDTO dto = new UserDTO();
        dto.setAccountId(userId);
        dto.setDepartmentCode(department);
        dto.setName("Sample User");
        return ResponseEntity.ok(dto);
    }

    @GetMapping("/{userId}/{department}")
    public ResponseEntity<UserDTO> getUserByPath(
            @PathVariable("userId") String userId,
            @PathVariable("department") String department) {
        UserDTO dto = new UserDTO();
        dto.setAccountId(userId);
        dto.setDepartmentCode(department);
        return ResponseEntity.ok(dto);
    }
}
