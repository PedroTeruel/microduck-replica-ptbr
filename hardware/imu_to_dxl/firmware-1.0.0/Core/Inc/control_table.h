#ifndef CONTROL_TABLE_H
#define CONTROL_TABLE_H
#include <stdint.h>
#include "protocol.h"
/* Custom read-only diagnostic register map, see README. Not servo telemetry. */
uint8_t control_table_read(void *user, uint16_t address, uint16_t length, uint8_t *out);
uint8_t control_table_write(void *user, uint16_t address, uint16_t length, const uint8_t *data);
#endif
