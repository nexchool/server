import { useState, useCallback } from "react";
import { classService } from "../services/classService";
import { ClassItem, ClassDetail, CreateClassDTO } from "../types";
import { Student } from "@/modules/students/types";
import { Teacher } from "@/modules/teachers/types";

export const useClasses = () => {
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [currentClass, setCurrentClass] = useState<ClassDetail | null>(null);
  const [unassignedStudents, setUnassignedStudents] = useState<Student[]>([]);
  const [unassignedTeachers, setUnassignedTeachers] = useState<Teacher[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchClasses = useCallback(async (params?: { academic_year_id?: string }) => {
    setLoading(true);
    setError(null);
    try {
      const data = await classService.getClasses(params);
      setClasses(data);
    } catch (err: any) {
      setError(err.message || "Failed to fetch classes");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchClassDetail = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await classService.getClassDetail(id);
      setCurrentClass(data);
      return data;
    } catch (err: any) {
      setError(err.message || "Failed to fetch class details");
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const createClass = useCallback(async (data: CreateClassDTO): Promise<ClassItem> => {
    setLoading(true);
    setError(null);
    try {
      const created = await classService.createClass(data);
      setClasses(prev => [...prev, created]);
      return created;
    } catch (err: any) {
      setError(err.message || "Failed to create class");
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const assignStudent = useCallback(async (classId: string, studentId: string) => {
    try {
      await classService.assignStudent(classId, studentId);
      await fetchClassDetail(classId);
    } catch (err: any) {
      setError(err.message || "Failed to assign student");
      throw err;
    }
  }, [fetchClassDetail]);

  const removeStudent = useCallback(async (classId: string, studentId: string) => {
    try {
      await classService.removeStudent(classId, studentId);
      await fetchClassDetail(classId);
    } catch (err: any) {
      setError(err.message || "Failed to remove student");
      throw err;
    }
  }, [fetchClassDetail]);

  const assignTeacher = useCallback(async (classId: string, teacherId: string, subject?: string) => {
    try {
      await classService.assignTeacher(classId, teacherId, subject);
      await fetchClassDetail(classId);
    } catch (err: any) {
      setError(err.message || "Failed to assign teacher");
      throw err;
    }
  }, [fetchClassDetail]);

  const removeTeacher = useCallback(async (classId: string, teacherId: string) => {
    try {
      await classService.removeTeacher(classId, teacherId);
      await fetchClassDetail(classId);
    } catch (err: any) {
      setError(err.message || "Failed to remove teacher");
      throw err;
    }
  }, [fetchClassDetail]);

  const fetchUnassignedStudents = useCallback(async (classId: string) => {
    try {
      const data = await classService.getUnassignedStudents(classId);
      setUnassignedStudents(data);
      return data;
    } catch (err: any) {
      setError(err.message);
      return [];
    }
  }, []);

  const fetchUnassignedTeachers = useCallback(async (classId: string) => {
    try {
      const data = await classService.getUnassignedTeachers(classId);
      setUnassignedTeachers(data);
      return data;
    } catch (err: any) {
      setError(err.message);
      return [];
    }
  }, []);

  return {
    classes,
    currentClass,
    unassignedStudents,
    unassignedTeachers,
    loading,
    error,
    fetchClasses,
    fetchClassDetail,
    createClass,
    assignStudent,
    removeStudent,
    assignTeacher,
    removeTeacher,
    fetchUnassignedStudents,
    fetchUnassignedTeachers,
  };
};
