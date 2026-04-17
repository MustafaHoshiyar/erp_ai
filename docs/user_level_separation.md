# User-Level Separation Implementation Plan

This document outlines the strategy for inheriting ERPNext permissions to separate "Owner" and "Manager" dashboards within a shared Workbook in Frappe Insights.

## Goal
To allow each ERPNext application (client) to have a shared "ERP AI Reports" workbook, while ensuring that "Managers" (standard users) only see dashboards they personally generated, and "Owners" (System Managers) can see all dashboards for that client.

## Proposed Strategy

### 1. Inherit ERPNext Authentication & Roles
- **Login Enhancement**: Update the `/api/login` endpoint in the AI Dashboard to fetch the user's ERPNext roles (e.g., `System Manager`).
- **Role Categories**:
    - **Owner**: Any user with the `System Manager` role.
    - **Manager**: Any user with standard/other roles.

### 2. Implementation in Frappe Insights (Backend)
- **Workbook**: Shared per ERPNext instance (Client).
- **Ownership Tracking**: When exporting a report to Frappe Insights, the `owner` field for the following DocTypes will be explicitly set to the creator's ERPNext email:
    - `Insights Query v3`
    - `Insights Chart v3`
    - `Insights Dashboard v3`
- **Dashboard Visibility**: "Owners" can see all dashboards in the shared workbook, while "Managers" are restricted to their own.

### 3. Backend & Frontend Updates
- **Backend (Python)**:
    - Modify the export functions in `frappe_insights.py` to accept and set the `owner` field.
    - Update the `/api/reports/insights-dashboards` endpoint to filter the dashboard list based on the user's email and role.
- **Frontend (JavaScript)**:
    - Store the user's role and email in `localStorage` upon login.
    - Pass the user's email to the export and list API endpoints.

## Required Site Configuration
To properly restrict "Managers" within the Frappe Insights UI, you must configure the following in your ERPNext site:
1. Go to **Role Permissions Manager**.
2. Select the **Manager** role and **Insights Dashboard v3** DocType.
3. Check the **"Only If Creator"** (Owner) permission.

---
*Created on 2026-04-01*
