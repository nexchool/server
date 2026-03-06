
export interface Student {
  id: string;
  user_id: string;
  name: string;
  email: string;
  profile_picture?: string;
  admission_number: string;
  academic_year?: string;
  academic_year_id?: string;
  roll_number?: number;
  class_id?: string;
  class_name?: string;
  date_of_birth?: string;
  gender?: string;
  phone?: string;
  address?: string;
  guardian_name?: string;
  guardian_relationship?: string;
  guardian_phone?: string;
  guardian_email?: string;
  created_at: string;
}

export interface Class {
  id: string;
  name: string;
  section: string;
  academic_year: string;
  teacher_id?: string;
  teacher_name?: string;
  created_at: string;
}

export interface CreateStudentDTO {
  // Required fields
  name: string;
  guardian_name: string;
  guardian_relationship: string;
  guardian_phone: string;
  
  // Academic: either class_id (derives academic year) or academic_year_id
  class_id?: string;
  academic_year_id?: string;
  
  // Optional fields
  admission_number?: string; // Auto-generated if not provided
  email?: string;
  phone?: string;
  date_of_birth?: string;
  gender?: string;
  roll_number?: number;
  address?: string;
  guardian_email?: string;
}

export interface StudentCredentials {
  username: string; // Admission number
  email: string; // Student email
  password: string; // First 3 letters + birth year
  must_reset: boolean;
}

export interface CreateStudentResponse {
  student: Student;
  credentials?: StudentCredentials;
}

export interface UpdateStudentDTO extends Partial<CreateStudentDTO> {}
