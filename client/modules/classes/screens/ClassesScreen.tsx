import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  ActivityIndicator,
  SafeAreaView,
  RefreshControl,
  TouchableOpacity,
  Alert,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useClasses } from "../hooks/useClasses";
import { usePermissions } from "@/modules/permissions/hooks/usePermissions";
import { useAcademicYearContext } from "@/modules/academics/context/AcademicYearContext";
import * as PERMS from "@/modules/permissions/constants/permissions";
import { CreateClassModal } from "../components/CreateClassModal";
import { Colors } from "@/common/constants/colors";
import { Spacing, Layout } from "@/common/constants/spacing";
import { ClassItem, CreateClassDTO } from "../types";

export default function ClassesScreen() {
  const router = useRouter();
  const { classes, loading, fetchClasses, createClass } = useClasses();
  const { hasPermission } = usePermissions();
  const { selectedAcademicYearId } = useAcademicYearContext();

  const canCreate = hasPermission(PERMS.CLASS_CREATE);
  const [modalVisible, setModalVisible] = useState(false);

  useEffect(() => {
    fetchClasses({ academic_year_id: selectedAcademicYearId || undefined });
  }, [selectedAcademicYearId, fetchClasses]);

  const handleClassPress = (cls: ClassItem) => {
    router.push(`/classes/${cls.id}` as any);
  };

  const handleCreateClass = async (data: CreateClassDTO) => {
    try {
      await createClass(data);
      setModalVisible(false);
      Alert.alert("Success", "Class created successfully");
      fetchClasses();
    } catch (error: any) {
      throw error;
    }
  };

  const renderClassItem = ({ item }: { item: ClassItem }) => (
    <TouchableOpacity
      style={styles.classCard}
      onPress={() => handleClassPress(item)}
      activeOpacity={0.7}
    >
      <View style={styles.classIcon}>
        <Ionicons name="school" size={24} color={Colors.primary} />
      </View>
      <View style={styles.classInfo}>
        <Text style={styles.className}>
          {item.name} - {item.section}
        </Text>
        <Text style={styles.classDetail}>{item.academic_year}</Text>
        <View style={styles.statsRow}>
          <View style={styles.stat}>
            <Ionicons name="people-outline" size={14} color={Colors.textSecondary} />
            <Text style={styles.statText}>{item.student_count || 0} students</Text>
          </View>
          <View style={styles.stat}>
            <Ionicons name="person-outline" size={14} color={Colors.textSecondary} />
            <Text style={styles.statText}>{item.teacher_count || 0} teachers</Text>
          </View>
        </View>
      </View>
      <Ionicons name="chevron-forward" size={20} color={Colors.textTertiary} />
    </TouchableOpacity>
  );

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Classes</Text>
        {canCreate && (
          <TouchableOpacity
            style={styles.addButton}
            onPress={() => setModalVisible(true)}
          >
            <Ionicons name="add" size={24} color={Colors.primary} />
          </TouchableOpacity>
        )}
      </View>

      {loading && classes.length === 0 ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color={Colors.primary} />
        </View>
      ) : (
        <FlatList
          data={classes}
          keyExtractor={(item) => item.id}
          renderItem={renderClassItem}
          contentContainerStyle={styles.listContent}
          refreshControl={
            <RefreshControl refreshing={loading} onRefresh={() => fetchClasses()} />
          }
          ListEmptyComponent={
            <View style={styles.center}>
              <Text style={styles.emptyText}>No classes found.</Text>
            </View>
          }
        />
      )}

      {canCreate && (
        <CreateClassModal
          visible={modalVisible}
          onClose={() => setModalVisible(false)}
          onSubmit={handleCreateClass}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.background },
  center: { flex: 1, justifyContent: "center", alignItems: "center", padding: Spacing.xl },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: Spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  headerTitle: { fontSize: 24, fontWeight: "bold", color: Colors.text },
  addButton: {
    padding: Spacing.sm,
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.md,
  },
  listContent: { padding: Spacing.md },
  classCard: {
    flexDirection: "row",
    alignItems: "center",
    padding: Spacing.md,
    backgroundColor: Colors.background,
    borderRadius: Layout.borderRadius.md,
    borderWidth: 1,
    borderColor: Colors.borderLight,
    marginBottom: Spacing.sm,
  },
  classIcon: {
    width: 48,
    height: 48,
    borderRadius: Layout.borderRadius.md,
    backgroundColor: Colors.backgroundSecondary,
    alignItems: "center",
    justifyContent: "center",
    marginRight: Spacing.md,
  },
  classInfo: { flex: 1 },
  className: { fontSize: 16, fontWeight: "600", color: Colors.text },
  classDetail: { fontSize: 13, color: Colors.textSecondary, marginTop: 2 },
  statsRow: { flexDirection: "row", marginTop: Spacing.xs, gap: Spacing.md },
  stat: { flexDirection: "row", alignItems: "center", gap: 4 },
  statText: { fontSize: 12, color: Colors.textSecondary },
  emptyText: { fontSize: 16, color: Colors.textSecondary },
});
