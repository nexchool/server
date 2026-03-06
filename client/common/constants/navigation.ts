/**
 * Navigation Configuration for Role-Based App
 * 
 * Defines which tabs are visible for each role and their configurations
 */

import { Ionicons } from '@expo/vector-icons';
import * as PERMS from '@/modules/permissions/constants/permissions';

export interface TabConfig {
  name: string;
  title: string;
  icon: keyof typeof Ionicons.glyphMap;
  iconOutline: keyof typeof Ionicons.glyphMap;
  requiredPermissions?: string[];  // If any of these permissions exist, show tab
  hideForRoles?: string[];  // Explicitly hide for certain roles
  /** Plan feature key (e.g. student_management). Tab hidden when this feature is disabled for the tenant's plan. */
  requiredPlanFeature?: string;
}

export const ALL_TABS: TabConfig[] = [
  {
    name: 'home',
    title: 'Home',
    icon: 'home',
    iconOutline: 'home-outline',
    // Visible to all authenticated users
  },
  {
    name: 'students',
    title: 'Students',
    icon: 'people',
    iconOutline: 'people-outline',
    requiredPermissions: [
      PERMS.STUDENT_READ_ALL,
      PERMS.STUDENT_READ_CLASS,
      PERMS.STUDENT_MANAGE,
    ],
    requiredPlanFeature: 'student_management',
  },
  {
    name: 'teachers',
    title: 'Teachers',
    icon: 'school',
    iconOutline: 'school-outline',
    requiredPermissions: [
      PERMS.TEACHER_READ,
      PERMS.TEACHER_MANAGE,
    ],
    requiredPlanFeature: 'teacher_management',
  },
  {
    name: 'classes',
    title: 'Classes',
    icon: 'library',
    iconOutline: 'library-outline',
    requiredPermissions: [
      PERMS.CLASS_READ,
      PERMS.CLASS_MANAGE,
    ],
    requiredPlanFeature: 'class_management',
  },
  {
    name: 'academics',
    title: 'Academics',
    icon: 'book',
    iconOutline: 'book-outline',
    requiredPermissions: [
      PERMS.STUDENT_READ,
      PERMS.GRADE_READ_SELF,
      PERMS.ATTENDANCE_READ_SELF,
      PERMS.ATTENDANCE_MARK,
      PERMS.GRADE_CREATE,
    ],
  },
  {
    name: 'activities',
    title: 'Activities',
    icon: 'calendar',
    iconOutline: 'calendar-outline',
    // Visible to all authenticated users
  },
  {
    name: 'finance',
    title: 'Finance',
    icon: 'wallet',
    iconOutline: 'wallet-outline',
    requiredPermissions: [PERMS.FINANCE_READ, PERMS.FINANCE_MANAGE],
    requiredPlanFeature: 'fees_management',
  },
  {
    name: 'profile',
    title: 'Profile',
    icon: 'person',
    iconOutline: 'person-outline',
    // Visible to all authenticated users
  },
];

/**
 * Get visible tabs for current user based on permissions and plan-enabled features.
 * Hides tabs when the tenant's plan has that feature disabled.
 */
export const getVisibleTabs = (
  permissions: string[],
  enabledFeatures: string[] = []
): TabConfig[] => {
  return ALL_TABS.filter(tab => {
    // Plan feature: hide tab if this feature is disabled for the tenant's plan
    if (tab.requiredPlanFeature) {
      if (enabledFeatures.length > 0 && !enabledFeatures.includes(tab.requiredPlanFeature)) {
        return false;
      }
    }

    // If no permissions required, show to everyone
    if (!tab.requiredPermissions || tab.requiredPermissions.length === 0) {
      return true;
    }

    // Check if user has any of the required permissions
    return tab.requiredPermissions.some(perm => {
      // Check exact permission
      if (permissions.includes(perm)) return true;

      // Check hierarchical permission (resource.manage)
      const resource = perm.split('.')[0];
      if (permissions.includes(`${resource}.manage`)) return true;

      // Check system.manage (super admin)
      if (permissions.includes(PERMS.SYSTEM_MANAGE)) return true;

      return false;
    });
  });
};

/**
 * Determine user role based on permissions (for UI logic)
 * Note: This is for UI purposes only. Backend always checks permissions.
 */
export const getUserRole = (permissions: string[]): string => {
  // Check for admin
  if (permissions.includes(PERMS.SYSTEM_MANAGE) || 
      permissions.includes(PERMS.USER_MANAGE)) {
    return 'Admin';
  }

  // Check for teacher
  if (permissions.includes(PERMS.ATTENDANCE_MARK) || 
      permissions.includes(PERMS.GRADE_CREATE)) {
    return 'Teacher';
  }

  // Check for parent
  if (permissions.includes(PERMS.FEE_PAY) || 
      permissions.includes(PERMS.FEE_READ_CHILD)) {
    return 'Parent';
  }

  // Default to student
  return 'Student';
};

/**
 * Check if user is in a specific role
 */
export const isAdmin = (permissions: string[]): boolean => {
  return permissions.includes(PERMS.SYSTEM_MANAGE) || 
         permissions.includes(PERMS.USER_MANAGE) ||
         permissions.includes(PERMS.ROLE_MANAGE);
};

export const isTeacher = (permissions: string[]): boolean => {
  return permissions.includes(PERMS.ATTENDANCE_MARK) ||
         permissions.includes(PERMS.GRADE_CREATE) ||
         permissions.includes(PERMS.ASSIGNMENT_CREATE);
};

export const isStudent = (permissions: string[]): boolean => {
  return permissions.includes(PERMS.GRADE_READ_SELF) ||
         permissions.includes(PERMS.ATTENDANCE_READ_SELF);
};

export const isParent = (permissions: string[]): boolean => {
  return permissions.includes(PERMS.FEE_PAY) ||
         permissions.includes(PERMS.GRADE_READ_CHILD);
};
