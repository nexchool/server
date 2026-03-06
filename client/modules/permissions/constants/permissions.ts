/**
 * Permission Constants
 * 
 * Centralized permission strings to avoid typos and ensure consistency
 */

// System Management
export const SYSTEM_MANAGE = 'system.manage';

// User Management
export const USER_CREATE = 'user.create';
export const USER_READ = 'user.read';
export const USER_UPDATE = 'user.update';
export const USER_DELETE = 'user.delete';
export const USER_MANAGE = 'user.manage';

// Role Management
export const ROLE_CREATE = 'role.create';
export const ROLE_READ = 'role.read';
export const ROLE_UPDATE = 'role.update';
export const ROLE_DELETE = 'role.delete';
export const ROLE_MANAGE = 'role.manage';

// Permission Management
export const PERMISSION_CREATE = 'permission.create';
export const PERMISSION_READ = 'permission.read';
export const PERMISSION_UPDATE = 'permission.update';
export const PERMISSION_DELETE = 'permission.delete';
export const PERMISSION_MANAGE = 'permission.manage';

// Attendance Management
export const ATTENDANCE_MARK = 'attendance.mark';
export const ATTENDANCE_READ_SELF = 'attendance.read.self';
export const ATTENDANCE_READ_CLASS = 'attendance.read.class';
export const ATTENDANCE_READ_ALL = 'attendance.read.all';
export const ATTENDANCE_UPDATE = 'attendance.update';
export const ATTENDANCE_DELETE = 'attendance.delete';
export const ATTENDANCE_MANAGE = 'attendance.manage';

// Student Management
export const STUDENT_CREATE = 'student.create';
export const STUDENT_READ = 'student.read';
export const STUDENT_READ_CLASS = 'student.read.class';
export const STUDENT_READ_ALL = 'student.read.all';
export const STUDENT_READ_SELF = 'student.read.self';
export const STUDENT_UPDATE = 'student.update';
export const STUDENT_UPDATE_SELF = 'student.update.self';
export const STUDENT_DELETE = 'student.delete';
export const STUDENT_MANAGE = 'student.manage';

// Grade Management
export const GRADE_CREATE = 'grade.create';
export const GRADE_READ_SELF = 'grade.read.self';
export const GRADE_READ_CLASS = 'grade.read.class';
export const GRADE_READ_CHILD = 'grade.read.child';
export const GRADE_READ_ALL = 'grade.read.all';
export const GRADE_UPDATE = 'grade.update';
export const GRADE_DELETE = 'grade.delete';
export const GRADE_MANAGE = 'grade.manage';

// Assignment Management
export const ASSIGNMENT_CREATE = 'assignment.create';
export const ASSIGNMENT_READ_SELF = 'assignment.read.self';
export const ASSIGNMENT_READ_CLASS = 'assignment.read.class';
export const ASSIGNMENT_READ_ALL = 'assignment.read.all';
export const ASSIGNMENT_UPDATE = 'assignment.update';
export const ASSIGNMENT_DELETE = 'assignment.delete';
export const ASSIGNMENT_SUBMIT = 'assignment.submit';
export const ASSIGNMENT_MANAGE = 'assignment.manage';

// Profile Management
export const PROFILE_READ_SELF = 'profile.read.self';
export const PROFILE_READ_ALL = 'profile.read.all';
export const PROFILE_UPDATE_SELF = 'profile.update.self';
export const PROFILE_UPDATE_ALL = 'profile.update.all';
export const PROFILE_MANAGE = 'profile.manage';

// Finance Management (RBAC uses finance.read, finance.manage)
export const FINANCE_READ = 'finance.read';
export const FINANCE_MANAGE = 'finance.manage';

// Finance Management (legacy fee permissions)
export const FEE_CREATE = 'fee.create';
export const FEE_READ_SELF = 'fee.read.self';
export const FEE_READ_CHILD = 'fee.read.child';
export const FEE_READ_ALL = 'fee.read.all';
export const FEE_UPDATE = 'fee.update';
export const FEE_DELETE = 'fee.delete';
export const FEE_PAY = 'fee.pay';
export const FEE_MANAGE = 'fee.manage';

// Teacher Management
export const TEACHER_CREATE = 'teacher.create';
export const TEACHER_READ = 'teacher.read';
export const TEACHER_UPDATE = 'teacher.update';
export const TEACHER_DELETE = 'teacher.delete';
export const TEACHER_MANAGE = 'teacher.manage';

// Class Management
export const CLASS_CREATE = 'class.create';
export const CLASS_READ = 'class.read';
export const CLASS_UPDATE = 'class.update';
export const CLASS_DELETE = 'class.delete';
export const CLASS_MANAGE = 'class.manage';

// Report Management
export const REPORT_READ_SELF = 'report.read.self';
export const REPORT_READ_CLASS = 'report.read.class';
export const REPORT_READ_ALL = 'report.read.all';
export const REPORT_GENERATE = 'report.generate';
export const REPORT_MANAGE = 'report.manage';

// Helper function to check if a permission belongs to a resource
export const isResourcePermission = (permission: string, resource: string): boolean => {
  return permission.startsWith(`${resource}.`);
};

// Helper function to get resource from permission
export const getResource = (permission: string): string => {
  return permission.split('.')[0];
};
