import { Router } from 'express';
import mongoose from 'mongoose';
import { generateDocuments, SUPPORTED_TYPES } from '../services/faker.js';

const router = Router();

// GET /api/generate/types  — list all supported field types
router.get('/types', (_req, res) => {
  res.json({ types: SUPPORTED_TYPES });
});

// POST /api/generate/preview  — return generated docs without saving
router.post('/preview', (req, res) => {
  const { schema, count = 5 } = req.body;
  if (!schema || typeof schema !== 'object') {
    return res.status(400).json({ error: 'schema is required and must be an object' });
  }
  const docs = generateDocuments(schema, Math.min(count, 100));
  res.json({ docs });
});

// POST /api/generate/save  — generate and insert into MongoDB collection
router.post('/save', async (req, res) => {
  const { schema, count = 10, collectionName } = req.body;
  if (!schema || typeof schema !== 'object') {
    return res.status(400).json({ error: 'schema is required' });
  }
  if (!collectionName || typeof collectionName !== 'string') {
    return res.status(400).json({ error: 'collectionName is required' });
  }

  const docs = generateDocuments(schema, Math.min(count, 1000));
  const collection = mongoose.connection.collection(collectionName);
  const result = await collection.insertMany(docs);

  res.json({ inserted: result.insertedCount, collectionName });
});

export default router;
