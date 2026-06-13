import { Router } from 'express';
import mongoose from 'mongoose';

const router = Router();

// GET /api/collections  — list all collections with document counts
router.get('/', async (_req, res) => {
  const db = mongoose.connection.db;
  const collections = await db.listCollections().toArray();
  const result = await Promise.all(
    collections.map(async (c) => ({
      name: c.name,
      count: await db.collection(c.name).countDocuments(),
    }))
  );
  res.json({ collections: result });
});

// GET /api/collections/:name  — paginated documents from a collection
router.get('/:name', async (req, res) => {
  const { name } = req.params;
  const page = Math.max(1, parseInt(req.query.page) || 1);
  const limit = Math.min(100, parseInt(req.query.limit) || 20);
  const skip = (page - 1) * limit;

  const collection = mongoose.connection.db.collection(name);
  const [docs, total] = await Promise.all([
    collection.find({}).skip(skip).limit(limit).toArray(),
    collection.countDocuments(),
  ]);

  res.json({ docs, total, page, limit });
});

// DELETE /api/collections/:name  — drop a collection
router.delete('/:name', async (req, res) => {
  const { name } = req.params;
  await mongoose.connection.db.collection(name).drop().catch(() => null);
  res.json({ dropped: name });
});

export default router;
