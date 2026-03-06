import { z } from "zod";

/**
 * Student Validation Schemas
 * 
 * These schemas validate student data for create and update operations.
 * They match the backend expectations exactly.
 */

// Base student schema with all possible fields
const studentBaseSchema = {
  // Required fields
  name: z.string().min(1, "Full name is required").max(120, "Name is too long"),
  guardian_name: z.string().min(1, "Guardian name is required").max(100, "Guardian name is too long"),
  guardian_relationship: z.string().min(1, "Guardian relationship is required").max(50, "Relationship is too long"),
  guardian_phone: z.string().min(1, "Guardian phone is required").max(20, "Phone number is too long"),
  
  // Academic: either class_id or academic_year_id required
  class_id: z.string().uuid("Invalid class ID").optional().or(z.literal("")),
  academic_year_id: z.string().uuid("Invalid academic year ID").optional().or(z.literal("")),
  
  // Optional fields
  admission_number: z.string().max(20, "Admission number is too long").optional(),
  email: z.string().email("Invalid email format").max(120, "Email is too long").optional().or(z.literal("")),
  phone: z.string().max(20, "Phone number is too long").optional().or(z.literal("")),
  date_of_birth: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Date must be in YYYY-MM-DD format").optional().or(z.literal("")),
  gender: z.string().max(10, "Gender is too long").optional().or(z.literal("")),
  roll_number: z.number().int("Roll number must be an integer").positive("Roll number must be positive").optional(),
  address: z.string().optional().or(z.literal("")),
  guardian_email: z.string().email("Invalid guardian email format").max(120, "Email is too long").optional().or(z.literal("")),
};

/**
 * Schema for creating a new student
 */
export const createStudentSchema = z.object({
  ...studentBaseSchema,
})
  .refine((data: any) => data.class_id?.trim() || data.academic_year_id?.trim(), {
    message: "Select a class or academic year",
    path: ["academic_year_id"],
  })
  .refine((data: any) => {
    if (data.email && data.email.trim() === "") return false;
    return true;
  }, {
    message: "Email cannot be empty if provided",
    path: ["email"],
  });

/**
 * Schema for updating an existing student
 * All fields are optional since we only update what's provided
 */
export const updateStudentSchema = z.object({
  name: z.string().min(1, "Full name is required").max(120, "Name is too long").optional(),
  academic_year_id: z.string().uuid("Invalid academic year ID").optional().or(z.literal("")).nullable(),
  guardian_name: z.string().min(1, "Guardian name is required").max(100, "Guardian name is too long").optional(),
  guardian_relationship: z.string().min(1, "Guardian relationship is required").max(50, "Relationship is too long").optional(),
  guardian_phone: z.string().min(1, "Guardian phone is required").max(20, "Phone number is too long").optional(),
  email: z.string().email("Invalid email format").max(120, "Email is too long").optional().or(z.literal("")),
  phone: z.string().max(20, "Phone number is too long").optional().or(z.literal("")),
  date_of_birth: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Date must be in YYYY-MM-DD format").optional().or(z.literal("")),
  gender: z.string().max(10, "Gender is too long").optional().or(z.literal("")),
  class_id: z.string().uuid("Invalid class ID").optional().or(z.literal("")).nullable(),
  roll_number: z.number().int("Roll number must be an integer").positive("Roll number must be positive").optional().nullable(),
  address: z.string().optional().or(z.literal("")),
  guardian_email: z.string().email("Invalid guardian email format").max(120, "Email is too long").optional().or(z.literal("")),
}).partial();

/**
 * Type exports for TypeScript
 */
export type CreateStudentInput = z.infer<typeof createStudentSchema>;
export type UpdateStudentInput = z.infer<typeof updateStudentSchema>;

/**
 * Helper function to validate and get user-friendly errors
 */
export function validateStudentData(data: unknown, isUpdate: boolean = false) {
  const schema = isUpdate ? updateStudentSchema : createStudentSchema;
  const result = schema.safeParse(data);
  
  if (!result.success) {
    // Convert Zod errors to field-level errors
    const fieldErrors: Record<string, string> = {};
    result.error.issues.forEach((err) => {
      const field = err.path[0] as string;
      if (field && !fieldErrors[field]) {
        fieldErrors[field] = err.message;
      }
    });
    
    return {
      valid: false,
      errors: fieldErrors,
      data: null,
    };
  }
  
  return {
    valid: true,
    errors: {},
    data: result.data,
  };
}
