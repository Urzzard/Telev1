-- ============================================
-- ESQUEMA INICIAL - SISTEMA DE LLAMADAS
-- ============================================

-- Tabla principal: empleados sincronizados
CREATE TABLE empleados (
    id SERIAL PRIMARY KEY,
    id_externo INTEGER UNIQUE NOT NULL,
    nombre VARCHAR(200) NOT NULL,
    documento VARCHAR(20),
    celular VARCHAR(20) NOT NULL,
    puesto VARCHAR(200),
    fecha_ingreso DATE,
    
    -- Control de llamadas (diseño simplificado)
    estado VARCHAR(20) DEFAULT 'PENDIENTE',  -- PENDIENTE (por llamar) · EN_LLAMADA (llamada activa) · EXITO (contactado ok) · TERMINADO (3 intentos fallidos)
    intentos INTEGER DEFAULT 0,
    
    -- Timestamps
    sincronizado_en TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    proxima_llamada TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Tabla de historial de llamadas
CREATE TABLE llamadas (
    id SERIAL PRIMARY KEY,
    empleado_id INTEGER REFERENCES empleados(id),
    intento INTEGER NOT NULL,
    resultado VARCHAR(30) NOT NULL,  -- en_curso (inicial) · completada · fallida · buzon
    duracion_segundos INTEGER DEFAULT 0,
    iniciada_en TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    finalizada_en TIMESTAMPTZ,
    notas TEXT
);

-- Configuración del sistema
CREATE TABLE configuracion (
    clave VARCHAR(50) PRIMARY KEY,
    valor TEXT NOT NULL,
    actualizado_en TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Valor inicial: último ID procesado
INSERT INTO configuracion (clave, valor) 
VALUES ('ultimo_id_externo', '170058');

-- Índices básicos
CREATE INDEX idx_empleados_estado ON empleados(estado);
CREATE INDEX idx_empleados_pendientes ON empleados(estado, intentos);

-- Mensaje de confirmación
DO $$ BEGIN RAISE NOTICE '✅ Base de datos inicializada'; END $$;


-- Tabla de conversaciones para fine-tuning
CREATE TABLE conversaciones (
    id SERIAL PRIMARY KEY,
    empleado_id INTEGER REFERENCES empleados(id),
    llamada_id INTEGER REFERENCES llamadas(id),
    turno INTEGER NOT NULL,
    rol VARCHAR(20) NOT NULL,  -- 'usuario' o 'asistente'
    texto TEXT NOT NULL,
    categoria VARCHAR(50),      -- horario, ubicacion, etc.
    confianza_vad FLOAT,        -- Para análisis de calidad de audio
    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_conversaciones_empleado ON conversaciones(empleado_id);
CREATE INDEX idx_conversaciones_llamada ON conversaciones(llamada_id);