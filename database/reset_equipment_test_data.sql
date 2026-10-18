DELETE FROM equipment_reservations;
DELETE FROM equipment_items;
INSERT INTO equipment_items (name, category, total_quantity, status) VALUES ('Projector', 'AV', 10, 'active');
